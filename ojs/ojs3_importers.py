from dateutil import parser as dateparser
from django.utils import timezone
from django.utils.html import strip_tags
from django.conf import settings

from core import files as core_files
from core import models as core_models
from identifiers import models as identifiers_models
from journal import models as journal_models
from submission import models as submission_models
from utils.logger import get_logger

from plugins.imports import models

logger = get_logger(__name__)

GALLEY_TYPES = {
    "pdf":  "pdf",
    "xml":  "xml",
    "html": "html",
    "PDF":  "pdf",
    "XML":  "xml",
    "HTML": "html",
}


def import_article(client, journal, article_dict):
    pub_article_dict = get_pub_article_dict(article_dict, client)
    article_dict["publication"] = pub_article_dict
    article = import_article_metadata(article_dict, journal, client)
    import_article_galleys(article, pub_article_dict, journal, client)


def import_issue(client, journal, issue_dict):
    issue, c = get_or_create_issue(issue_dict, journal)
    if c:
        logger.info("Created Issue %s from OJS ID %s", issue, issue_dict["id"])
    else:
        logger.info("Updating Issue %s from OJS ID %s", issue, issue_dict["id"])

    for section_dict in issue_dict["sections"]:
        section = import_section(section_dict, issue, client)

    for order, article_dict in enumerate(issue_dict["articles"]):
        article_dict["publication"] = get_pub_article_dict(article_dict, client)
        article, c = get_or_create_article(article_dict, journal)
        article.primary_issue = issue
        article.save()
        issue.articles.add(article)
        journal_models.ArticleOrdering.objects.update_or_create(
            section=article.section,
            issue=issue,
            article=article,
            defaults={"order": order}
        )
    if issue_dict["coverImageUrl"].values():
        django_file = client.fetch_file(delocalise(issue_dict["coverImageUrl"]))
        issue.cover_image.save(django_file.name or "cover.graphic", django_file)
        issue.large_image.save(django_file.name or "cover.graphic", django_file)
    
    issue.save()
    return issue


def import_section(section_dict, issue, client):
    section_id = section_dict["id"]
    tracked_section, c = update_or_create_section(
        issue.journal, section_id, section_dict)
    if c:
        logger.info("Created Section %s" % tracked_section.section)
    else:
        logger.info("Updating Section %s" % tracked_section.section)
    
    journal_models.SectionOrdering.objects.update_or_create(
        issue=issue,
        section=tracked_section.section,
        defaults={
            "order": section_dict.get("seq") or 0,
        }
    )

    return tracked_section.section


def import_article_metadata(article_dict, journal, client):
    logger.info("Processing OJS ID %s" % article_dict["id"])
    article, created = get_or_create_article(article_dict, journal)
    if created:
        logger.info("Created article %d" % article.pk)
    else:
        logger.info("Updating article %d" % article.pk)

    # Update Metadata
    article.abstract = delocalise(article_dict["publication"]["abstract"])
    article.pages = article_dict["publication"].get("pages")
    if article_dict["publication"].get("datePublished"):
        date_published = timezone.make_aware(
            dateparser.parse(article_dict['dateSubmitted']).replace(hour=12)
        )
        article.date_published = date_published
        article.stage = submission_models.STAGE_PUBLISHED
    license_url = article_dict["publication"].get(
        "license", "").replace("http:", "https:")
    if license_url:
        article.license, _ = submission_models.Licence.objects.get_or_create(
            journal=article.journal,
            url=license_url,
            defaults={
                "name": "Imported License",
                "short_name": "imported",
            }
        )

    # Add to section with given ojs sectionId
    ojs_section, _ = update_or_create_section(
        journal, article_dict["publication"]["sectionId"],
    )
    article.section = ojs_section.section

    article.save()

    # Add keywords
    keywords = delocalise(article_dict["publication"]["keywords"])
    if keywords:
        logger.debug("Importing Keywords %s", keywords)
        for i, keyword in enumerate(keywords):
            if keyword:
                keyword = strip_tags(keyword)
                word, _ = submission_models.Keyword.objects.get_or_create(
                    word=keyword)
                submission_models.KeywordArticle.objects.update_or_create(
                    keyword=word,
                    article=article,
                    defaults={"order": i},
                )

    # Add authors
    for author in article_dict["publication"]["authors"]:
        create_frozen_record(author, article)

    return article


def import_article_galleys(article, publication, journal, client):
    for galley in publication["galleys"]:
        galley_file = import_file(galley["file"], client, article)
        
        new_galley, c = core_models.Galley.objects.get_or_create(
            article=article,
            type=GALLEY_TYPES.get(galley.get("label"), "other"),
            defaults={
                "label": galley.get("label"),
                "file": galley_file,
            },
        )


def import_file(file_json, client, article, label=None, file_name=None, owner=None):
    if not label:
        label = file_json.get("label", "file")
    if not file_name:
        file_name = (file_json["name"])
    django_file = client.fetch_file(file_json["url"])
    janeway_file = core_files.save_file_to_article(
        django_file, article, owner or article.owner, label=label or file_json["label"]
    )
    if file_json["mimetype"]:
        janeway_file.mime_type = file_json["mimetype"]
    if file_json["createdAt"]:
        janeway_file.date_uploaded = attempt_to_make_timezone_aware(
            file_json["createdAt"])
    if file_json["updatedAt"]:
        core_models.File.objects.filter(id=janeway_file.pk).update(
            date_modified=attempt_to_make_timezone_aware(file_json["updatedAt"])
        )
    janeway_file.original_filename = file_name
    janeway_file.save()

        return janeway_file


def get_or_create_issue(issue_dict, journal):
    issue_type = journal_models.IssueType.objects.get(
        journal=journal, code='issue')
    issue, c = journal_models.Issue.objects.update_or_create(
        volume=issue_dict.get("volume", 0),
        issue=issue_dict.get("number"),
        journal=journal,
        defaults={
            "issue_title": (
                delocalise(issue_dict["title"])
                #or issue_dict["identification"]
                or ""
            ),
            "issue_type": issue_type,
            "issue_description": delocalise(issue_dict["description"]) or None,
            "date": timezone.now().replace(year=issue_dict["year"])
        }
    )
    return issue, c


def get_or_create_article(article_dict, journal):
    """Get or create article, looking up by OJS ID or DOI"""
    created = False
    date_started = timezone.make_aware(
        dateparser.parse(article_dict['dateSubmitted'])
    )

    doi = article_dict.get("pub-id::doi")
    ojs_id = article_dict["id"]

    if doi and identifiers_models.Identifier.objects.filter(
        id_type="doi",
        identifier=doi,
        article__journal=journal,
    ).exists():
        article = identifiers_models.Identifier.objects.get(
            id_type="doi",
            identifier=doi,
            article__journal=journal,
        ).article
    elif identifiers_models.Identifier.objects.filter(
        id_type="ojs_id",
        identifier=ojs_id,
        article__journal=journal,
    ).exists():
        article = identifiers_models.Identifier.objects.get(
            id_type="ojs_id",
            identifier=ojs_id,
            article__journal=journal,
        ).article
    else:
        created = True
        article = submission_models.Article(
            journal=journal,
            title=delocalise(article_dict["publication"]['fullTitle']),
            language=article_dict.get('locale'),
            stage=submission_models.STAGE_UNASSIGNED,
            is_import=True,
            date_submitted=date_started,
        )
        article.save()
        if doi:
            identifiers_models.Identifier.objects.create(
                id_type="doi",
                identifier=doi,
                article=article,
            )
        identifiers_models.Identifier.objects.create(
            id_type="ojs_id",
            identifier=ojs_id,
            article=article,
        )
    return article, created


def get_pub_article_dict(article_dict, client):
    """ Get the published article metadata

    OJS 3 API returns versions of the metadata under the "publications" attr.
    there is another attribute called currentPublicationId that points to the 
    currently active version of the metadata. This function uses this ID to 
    retrieve the publication from the dedicated API endpoint, since that object
    has more metadata than the one retrieved from /submissions
    """
    return client.get_publication(
        article_dict["id"], article_dict["currentPublicationId"]
    )

def update_or_create_section(journal, ojs_section_id, section_dict=None):
    imported, created = models.OJS3Section.objects.get_or_create(
        journal=journal,
        ojs_id=ojs_section_id,
    )
    if not imported.section:
        section = submission_models.Section.objects.create(
            name=ojs_section_id,
            journal=journal,
        )
        imported.section = section
        imported.save()

    if section_dict:
        section = imported.section
        section_name_translations = get_localised(section_dict["title"], prefix="name")
        section.__dict__.update(section_name_translations)
        section.save()

    return imported, created


def create_frozen_record(author, article):
    """ Creates a frozen record for the article from author metadata

    We create a frozen record that is not linked to a user
    account. This is because email addresses are not unique for author
    records on OJS, so there will be only a single account for all those
    authors which would then update itself instead of creating a new record
    :param author: an author object from OJS
    :param article: an instance of submission.models.Article
    """
    frozen_dict = {
        'article': article,
        'first_name': delocalise(author["givenName"]),
        'last_name': delocalise(author["familyName"]),
        'institution': delocalise(author["affiliation"]) or '',
        'order': author["seq"],
    }
    frozen, created = submission_models.FrozenAuthor.objects.get_or_create(
        **frozen_dict)
    if created:
        logger.debug("Added Frozen Author %s", frozen_dict)
    else:
        logger.debug("Updated Frozen Author %s", frozen_dict)
    return frozen, created


def delocalise(localised):
    """ Given a localised object, return the best possible value"""
    with_value = {k.split("_")[0]: v for k, v in localised.items() if v}
    if with_value:
        if settings.LANGUAGE_CODE in with_value:
            return with_value[settings.LANGUAGE_CODE]
        return next(iter(with_value.values()))
        
    return None

def get_localised(localised, prefix=None):
    """ Gets a localised OJS object in a format understandable by janeway
    e.g: {"en_US": "value"} => {"en" => "value"}
    :param localised: The localised object to transform.
    :param prefix: An optional prefix to add to the returned value. Useful for
        translating Modeltranslation objects (e.g: {"name_en" => "value"})
    """
    langs = dict(settings.LANGUAGES)

    transformed = {
        # "en_US" => "prefix_en"
        k.split("_")[0]: v for k, v in localised.items()
        if k.split("_")[0] in langs
    }
    if settings.LANGUAGE_CODE not in transformed:
        #transformed[settings.LANGUAGE_CODE] = next(iter(transformed.values()))
        pass

    if prefix:
        transformed = {
            # "en_US" => "prefix_en"
            "%s_%s" % (prefix, k.split("_")[0]): v 
            for k, v in transformed.items()
            if k.split("_")[0] in langs
        }
    return transformed


def attempt_to_make_timezone_aware(datetime):
    if datetime:
        dt = dateparser.parse(datetime)
        # We use 12 to avoid changing the date when the time is 00:00 with no tz
        return timezone.make_aware(dt.replace(hour=12))
    else:
        return None
