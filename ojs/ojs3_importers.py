from dateutil import parser as dateparser
from django.utils import timezone
from django.utils.html import strip_tags
from django.conf import settings
from django.core.management import call_command
from django.core.exceptions import ObjectDoesNotExist

from cms import models as cms_models
from core import files as core_files
from core import logic as core_logic
from core import models as core_models
from identifiers import models as identifiers_models
from journal import models as journal_models
from submission import models as submission_models
from utils.logger import get_logger
from utils import setting_handler

from plugins.imports import models

"""
1 // Define the file stage identifiers.
17  define('SUBMISSION_FILE_SUBMISSION', 2);
  1 define('SUBMISSION_FILE_NOTE', 3);
  2 define('SUBMISSION_FILE_REVIEW_FILE', 4);
  3 define('SUBMISSION_FILE_REVIEW_ATTACHMENT', 5);
  4 //------SUBMISSION_FILE_REVIEW_REVISION defined below (FIXME: re-order before release)
  5 define('SUBMISSION_FILE_FINAL', 6);
  6 define('SUBMISSION_FILE_COPYEDIT', 9);
  7 define('SUBMISSION_FILE_PROOF', 10);
  8 define('SUBMISSION_FILE_PRODUCTION_READY', 11);
  9 define('SUBMISSION_FILE_ATTACHMENT', 13);
 10 define('SUBMISSION_FILE_REVIEW_REVISION', 15);
 11 define('SUBMISSION_FILE_DEPENDENT', 17);
 12 define('SUBMISSION_FILE_QUERY', 18);
 13 define('SUBMISSION_FILE_INTERNAL_REVIEW_FILE', 19);
 14 define('SUBMISSION_FILE_INTERNAL_REVIEW_REVISION', 20);
"""


#Role IDs
ROLE_JOURNAL_MANAGER = 16
ROLE_SECTION_EDITOR = 17
ROLE_REVIEWER = 4096
ROLE_ASSISTANT = 4097 #  Production manager
ROLE_AUTHOR = 65536
ROLE_READER = 1048576
ROLE_SUBSCRIPTION_MANAGER = 2097152

ROLES_MAP = {
    ROLE_JOURNAL_MANAGER: "editor",
    ROLE_SECTION_EDITOR: "section-editor",
    ROLE_REVIEWER: "reviewer",
    ROLE_ASSISTANT: "production",
}


class DummyRequest():
    def __init__(self, user=None, files=None, journal=None):
        self.user = user
        self.FILES = files
        self.journal=journal


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
        if not article.date_published:
            article.date_published = issue.date
        article.save()
        issue.articles.add(article)
        journal_models.ArticleOrdering.objects.update_or_create(
            section=article.section,
            issue=issue,
            article=article,
            defaults={"order": order}
        )
    if issue_dict["coverImageUrl"].values():
        url = delocalise(issue_dict["coverImageUrl"])
        if url:
            django_file = client.fetch_file(url)
            if django_file:
                issue.cover_image.save(
                    django_file.name or "cover.graphic", django_file)
                issue.large_image.save(
                    django_file.name or "cover.graphic", django_file)

    if issue_dict["galleys"]:
        galley_id = issue_dict["galleys"][-1].get("id")
        django_file = client.get_issue_galley(issue_dict["id"], galley_id)
        if django_file:
            logger.info("Importing Issue galley %s into %s", galley_id, issue)
            try:
                issue_galley = journal_models.IssueGalley.objects.get(
                    issue=issue,
                )
                issue_galley.replace_file(django_file)
            except journal_models.IssueGalley.DoesNotExist:
                issue_galley = journal_models.IssueGalley(
                    issue=issue,
                )
                file_obj = core_files.save_file(
                    DummyRequest(journal=journal),
                    django_file,
                    label=issue.issue_title,
                    public=True,
                    path_parts=(journal_models.IssueGalley.FILES_PATH, issue.pk),
                )
                issue_galley.file = file_obj
                issue_galley.save()

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
    abstract_translations = get_localised(
        article_dict["publication"]["abstract"], prefix="abstract",
    )
    article.__dict__.update(abstract_translations)

    title_translations = get_localised(
        article_dict["publication"]["fullTitle"], prefix="title",
    )
    article.__dict__.update(title_translations)

    article.page_numbers = article_dict["publication"]["pages"]
    if article_dict["publication"].get("datePublished"):
        date_published = timezone.make_aware(
            dateparser.parse(article_dict['dateSubmitted']).replace(hour=12)
        )
        article.date_published = date_published
        article.stage = submission_models.STAGE_PUBLISHED
    license_url = article_dict["publication"]["licenseUrl"] or ''
    license_url = license_url.replace("http:", "https:")
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
        if galley["urlRemote"]:
            article.is_remote = True
            article.remote_url = galley["urlRemote"]
            article.save()
        elif not galley["file"]:
            # Ghost galley with no file
            continue
        else:
            galley_file = import_file(galley["file"], client, article)
            if galley_file:
                new_galley, c = core_models.Galley.objects.get_or_create(
                    article=article,
                    type=GALLEY_TYPES.get(galley.get("label"), "other"),
                    defaults={
                        "label": galley.get("label"),
                        "file": galley_file,
                    },
                )
            else:
                logger.error("Unable to fetch Galley %s" % galley["file"])

def import_user(user_dict, journal):
    account, created = core_models.Account.objects.get_or_create(
        email=user_dict["email"],
        defaults = {
            "first_name": delocalise(user_dict["givenName"]),
            "last_name": delocalise(user_dict["familyName"]),
        }
    )
    if user_dict["biography"] and not account.biography:
        account.biography = delocalise(user_dict["biography"])
    if user_dict["signature"] and not account.signature:
        account.signature = delocalise(user_dict["signature"])
    if user_dict["orcid"] and not account.orcid:
        orcid = user_dict["orcid"].split("orcid.org/")[-1] or None
        account.orcid = orcid
    if user_dict["disabled"] is True:
        account.active = False
    if user_dict["country"]:
        account.country = core_models.Country.objects.filter(
            name=user_dict["country"]
        ).first()

    import_user_roles(user_dict, account, journal)
    for interest in user_dict["interests"]:
        account.interest.get_or_create(name=interest["interest"])

    return account, created


def import_user_roles(user_dict, account, journal):
    account.add_account_role('author', journal)
    for group in user_dict["groups"]:
        if group["roleId"] in ROLES_MAP:
            account.add_account_role(ROLES_MAP[group["roleId"]], journal)


def import_file(file_json, client, article, label=None, file_name=None, owner=None):
    if not label:
        label = file_json.get("label", "file")
    if not file_name:
        file_name = delocalise(file_json["name"])
    django_file = client.fetch_file(file_json["url"])
    if django_file:
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
    date_published = timezone.make_aware(
        dateparser.parse(issue_dict['datePublished'])
    )
    if date_published and issue_dict["year"]:
        date_published = date_published.replace(year=issue_dict["year"])
    issue, c = journal_models.Issue.objects.update_or_create(
        volume=issue_dict.get("volume", 0),
        issue=issue_dict.get("number"),
        journal=journal,
        defaults={
            "issue_title": (
                delocalise(issue_dict["title"])
                or ""
            ),
            "issue_type": issue_type,
            "issue_description": delocalise(issue_dict["description"]) or None,
            "date": date_published,
        }
    )
    return issue, c


def get_or_create_article(article_dict, journal):
    """Get or create article, looking up by OJS ID or DOI"""
    created = False
    date_started = timezone.make_aware(
        dateparser.parse(article_dict['dateSubmitted'])
    )

    doi = (
        article_dict.get("pub-id::doi")
        or article_dict["publication"].get("pub-id::doi")
    )
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
            title=delocalise(
                article_dict["publication"]['fullTitle']
                or "NO TITLE"
            ),
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


def import_journal_metadata(client, journal_dict):
    journal = get_or_create_journal(journal_dict)
    journal.issn = journal_dict["onlineIssn"]
    description = delocalise(journal_dict["description"])
    journal.description = description
    journal.save()

    import_localised_journal_setting(
        journal_dict["description"], "general", "journal_description", journal)

    import_localised_journal_setting(
        journal_dict["about"], "general", "focus_and_scope", journal)

    import_localised_journal_setting(
        journal_dict["authorGuidelines"],
        "general", "submission_checklist", journal,
    )

    if journal_dict.get("disableSubmissions", False) is True:
        setting_handler.save_setting(
            "general", "disable_journal_submission", journal, True)

    import_localised_journal_setting(
        journal_dict["publicationFeeDescription"],
        "general", "publication_fees", journal,
    )

    try:
        setting_handler.get_setting("general", "open_access_policy", journal=None)
    except ObjectDoesNotExist:
        setting_handler.create_setting(
            "general", "open_access_policy",
            type='text',
            pretty_name="Open Access Policy",
            description="Open Access Policy",
            is_translatable=True,
        )
        setting_handler.save_setting(
            "general", "open_access_policy",
            journal=None,
            value="",
        )

    setting = import_localised_journal_setting(
        journal_dict["openAccessPolicy"],
        "general", "open_access_policy", journal,
    )
    if setting and setting.value:
        item, created = cms_models.SubmissionItem.objects.get_or_create(
            title="Open Access",
            journal=journal,
        )
        item.existing_setting = setting.setting
        item.save()

    import_journal_images(client, journal, journal_dict)

    return journal


def import_localised_journal_setting(setting_dict, setting_group, setting_name, journal):
    localised = get_localised(setting_dict, prefix="value")
    if any(localised.values()):
        # ensure setting value exists
        setting_handler.save_setting(setting_group, setting_name, journal, "")
        setting_value = setting_handler.get_setting(
            setting_group, setting_name, journal, default=False)
        setting_value.__dict__.update(
            get_localised(setting_dict, prefix="value")
        )
        setting_value.save()

        return setting_value
    return None


def import_journal_images(client, journal, journal_dict):
    journal_id = journal_dict["id"]

    favicon_filename = delocalise(journal_dict["favicon"])
    if favicon_filename:
        favicon = (
            client.fetch_public_file(journal_id, favicon_filename.get("name"))
             or client.fetch_public_file(
                 journal_id, favicon_filename.get("uploadName"))
        )
        if favicon:
            journal.favicon.save(favicon_filename.get("name"), favicon)

    journal_filename = delocalise(journal_dict["journalThumbnail"])
    if journal_filename:
        journal_cover = (
            client.fetch_public_file(journal_id, journal_filename.get("name"))
            or client.fetch_public_file(
                journal_id, journal_filename.get("uploadName"))
        )
        if journal_cover:
            journal.default_cover_image.save(journal_filename.get("name"), journal_cover)
            journal.default_large_image.save(journal_filename.get("name"), journal_cover)

    header_f = delocalise(journal_dict["pageHeaderLogoImage"])
    if header_f:
        header_image = (
            client.fetch_public_file(journal_id, header_f.get("name"))
            or client.fetch_public_file(journal_id, header_f.get("uploadName"))
        )
        if header_image:
            journal.header_image.save(header_f.get("name"), header_image)
            dummy_request = DummyRequest(
                files={"default_thumbnail": header_image},
                journal=journal,
            )
            core_logic.handle_default_thumbnail(
                dummy_request, journal, '')

    journal.save()

    return journal


def get_or_create_journal(journal_dict):
    code = journal_dict["urlPath"].lower()
    try:
        return journal_models.Journal.objects.get(code=code)
    except journal_models.Journal.DoesNotExist:
        name = delocalise(journal_dict["name"])
        default_domain = "localhost/%s" % code
        call_command(
            "install_journal",
            journal_code=code,
            journal_name=name,
            base_url=default_domain,
        )
        return journal_models.Journal.objects.get(code=code)


def import_editorial_team(journal_dict, journal):
    html = delocalise(journal_dict["editorialTeam"])
    if html:
        core_models.EditorialGroup.objects.update_or_create(
            name="Editorial Team",
            journal=journal,
            defaults={
                "description": html,
            }
        )


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
        transformed[settings.LANGUAGE_CODE] = next(iter(transformed.values()))

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
