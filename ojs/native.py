import bs4
from bs4 import BeautifulSoup

from django.utils.html import strip_tags
from django.core.files.base import ContentFile

from plugins.imports import common, models
from plugins.imports.ojs.importers import GALLEY_TYPES
from plugins.imports.ojs import importers
from plugins.imports import utils
from core import models as core_models, files
from journal import models as journal_models
from submission import models as submission_models
from utils import shared
from identifiers import models as ident_models


def import_users(xml_content, journal):
    users_soup = BeautifulSoup(xml_content, 'lxml')
    users = users_soup.findAll('user')
    accounts = list()

    for user in users:
        try:
            country = core_models.Country.objects.get(
                code=common.get_text_or_none(user, 'country'),
            )
        except core_models.Country.DoesNotExist:
            country = None
        email = common.get_text_or_none(user, 'email').lower().strip()
        interests = common.get_text_or_none(user, 'review_interests')
        user_groups_soup = user.findAll('user_group_ref')
        user_groups = [group.text for group in user_groups_soup]
        defaults = {
            'first_name': common.get_text_or_none(user, 'givenname'),
            'last_name': common.get_text_or_none(user, 'familyname'),
            'institution': common.get_text_or_none(user, 'affiliation'),
            'country': country,
            'biography': common.get_text_or_none(user, 'biography'),
            'is_active': True,
            'email': email,
        }
        account, created = core_models.Account.objects.update_or_create(
            username=email,
            defaults=defaults
        )
        if created:
            print(f'Account with email {email} created.')
            account.set_password(shared.generate_password(password_length=20))
            account.save()
        else:
            print(f'Account with email {email} updated.')
        if interests:
            for interest in interests.split(','):
                try:
                    new_interest, c = core_models.Interest.objects.get_or_create(
                        name=interest,
                    )
                except core_models.Interest.MultipleObjectsReturned:
                    new_interest = core_models.Interest.objects.filter(
                        name=interest,
                    ).first()
                account.interest.add(new_interest)
        if user_groups:
            role_slugs = common.map_ojs_roles_to_janeway_role_slugs(
                user_groups
            )
            for slug in role_slugs:
                account.add_account_role(
                    slug,
                    journal,
                )
        accounts.append(account)
    return accounts


def import_issues(xml_content, journal, owner, stage):
    souped_xml = bs4.BeautifulSoup(xml_content, 'lxml')

    # find each of the import sections we need
    issue_soup = souped_xml.findAll('issue')

    for issue in issue_soup:
        section_soup = issue.findAll('section')
        article_soup = issue.findAll('article')

        issue = import_issue(issue, journal)
        import_sections(section_soup, journal)
        articles_imported, articles_updated = import_articles(
            article_soup,
            journal,
            owner,
            stage,
            issue,
        )
        return articles_imported, articles_updated


def import_issue(issue_soup, journal):
    volume_number = common.get_text_or_none(issue_soup, 'volume')
    issue_number = common.get_text_or_none(issue_soup, 'number')
    year = common.get_text_or_none(issue_soup, 'year')
    description = common.get_text_or_none(issue_soup, 'description')
    date_published = utils.get_aware_datetime(
        common.get_text_or_none(issue_soup, 'date_published')
    )

    issue_type = journal_models.IssueType.objects.get(
        code='issue',
        journal=journal,
    )

    issue, created = journal_models.Issue.objects.update_or_create(
        journal=journal,
        volume=volume_number,
        issue=issue_number or 0,
        date=date_published,
        issue_type=issue_type,
        defaults={
            'issue_description': description,
        }
    )

    if created:
        print(f'Created new issue: {issue.display_title}')
    else:
        print(f'Updated issue: {issue.display_title}')

    return issue


def import_sections(section_soup, journal):
    for section in section_soup:
        indexing = common.int_string_to_bool(
            section.attrs.get('meta_indexed')
        )
        editor_restricted = common.int_string_to_bool(
            section.attrs.get('editor_restricted')
        )
        section_ref = section.attrs.get('ref')
        defaults = {
            'indexing': indexing,
            'public_submissions': True if not editor_restricted else False,
            'sequence': int(section.attrs.get('seq', 0)),
        }
        section, created = submission_models.Section.objects.get_or_create(
            journal=journal,
            name=common.get_text_or_none(section, 'title'),
            defaults=defaults,
        )
        models.OJS3Section.objects.get_or_create(
            journal=journal,
            ojs_ref=section_ref,
            section=section,
        )
        if created:
            print(f'Created new section {section.name}.')
        else:
            print(f'Section {section.name} already found.')


def get_article(identifiers, journal):
    doi = identifiers.get('doi')
    ojs_id = identifiers.get('id')
    article = None

    # attempt to get the article via the DOI and, if no matching DOI found,
    # try to fetch by the ojs_id. If neither is found then the article
    # is assumed not to exist in Janeway.
    if doi:
        article = submission_models.Article.get_article(
            journal,
            'doi',
            doi,
        )
    if ojs_id and not article:
        article = submission_models.Article.get_article(
            journal,
            'ojs_id',
            id,
        )
    return article


def import_articles(article_soup, journal, owner, stage, issue):
    articles_imported = list()
    articles_updated = list()
    for article in article_soup:
        publication_soup = article.find('publication')

        article_dict = {
            'title': get_title(article),
            'abstract': common.get_text_or_none(article, 'abstract'),
            'license': get_license(
                common.get_text_or_none(publication_soup, 'licenseurl'),
                journal,
            ),
            'date_submitted': utils.get_aware_datetime(
                article.attrs.get('date_submitted')
            ),
            'rights': common.get_text_or_none(article, 'copyrightholder'),
            'page_numbers': common.get_text_or_none(article, 'pages'),
            'date_published': utils.get_aware_datetime(
                publication_soup.attrs.get('date_published'),
            ),
            'section': get_section(publication_soup, journal),
        }

        identifiers = get_identifiers(publication_soup)
        keywords = get_keywords(publication_soup)
        author_data = get_authors(publication_soup)

        article_obj = get_article(
            identifiers,
            journal,
        )

        if article_obj:
            submission_models.Article.objects.filter(
                pk=article_obj.pk,
            ).update(
                **article_dict,
            )
            articles_updated.append(
                article_obj,
            )
        else:
            article_obj = submission_models.Article.objects.create(
                journal=journal,
                owner=owner,
                title=article_dict.get('title'),
                abstract=article_dict.get('abstract'),
                section=article_dict.get('section'),
                rights=article_dict.get('rights'),
                license=article_dict.get('license'),
                page_numbers=article_dict.get('page_numbers'),
                date_submitted=article_dict.get('date_submitted'),
                date_published=article_dict.get('date_published'),
                stage=stage,
                is_import=True,
            )

            articles_imported.append(
                article_obj,
            )
        set_article_issue(article_obj, issue)
        set_article_keywords(article_obj, keywords)
        set_article_identifiers(article_obj, identifiers)
        create_submission_files(article_obj, article)
        create_galleys(article_obj, publication_soup)

        emails = set()
        for author in sorted(author_data, key=lambda x: x.get('sequence', 1)):
            author_record, _ = importers.get_or_create_account(
                author,
                update=True,
            )
            article_obj.authors.add(author_record)
            order, _ = submission_models.ArticleAuthorOrder.objects.get_or_create(
                article=article_obj,
                author=author_record,
            )
            order.order = author.get("sequence", 999)
            importers.create_frozen_record(
                author_record,
                article_obj,
                emails,
            )

    return articles_imported, articles_updated


def get_section(publication_soup, journal):
    section_ref = publication_soup.attrs.get('section_ref')
    try:
        ojs3_section_link = models.OJS3Section.objects.get(
            journal=journal,
            ojs_ref=section_ref,
        )
        return ojs3_section_link.section
    except models.OJS3Section.DoesNotExist:
        # grab the default article section
        return submission_models.Section.objects.get_or_create(
            name='Article',
            plural='Articles',
            journal=journal,
        )


def get_license(license_url, journal):
    if license_url:
        if license_url.endswith("/"):
            license_url = license_url[:-1]
        license_url = license_url.replace("http:", "https:")
    _license, _ = submission_models.Licence.objects.get_or_create(
        journal=journal,
        url=license_url,
        defaults={
            "name": "Imported License",
            "short_name": "imported",
        }
    )
    return _license


def get_identifiers(publication_soup):
    identifiers = publication_soup.findAll('id')
    id_dict = {}

    for id in identifiers:
        id_dict[id.attrs.get('type')] = id.text

    return id_dict


def get_keywords(publication_soup):
    keywords = publication_soup.findAll('keyword')
    return [
        keyword.text for keyword in keywords
    ]


def get_authors(publication_soup):
    authors = publication_soup.findAll('author')
    author_list = []

    for author in authors:
        author_list.append(
            {
                'first_name': common.get_text_or_none(author, 'givenname'),
                'middle_name': '',
                'last_name': common.get_text_or_none(author, 'familyname'),
                'country': common.get_text_or_none(author, 'country'),
                'email': common.get_text_or_none(author, 'email'),
                'biography': common.get_text_or_none(author, 'biography'),
                'institution': None,
                'affiliation': None,
                'sequence': author.attrs.get('seq'),
            }
        )

    return author_list


def set_article_issue(article, issue):
    issue.articles.add(article)
    article.primary_issue = issue
    article.save()


def set_article_keywords(article, keywords):
    if keywords:
        for i, keyword in enumerate(keywords):
            if keyword:
                keyword = strip_tags(keyword)
                word, _ = submission_models.Keyword.objects.get_or_create(
                    word=keyword,
                )
                submission_models.KeywordArticle.objects.update_or_create(
                    keyword=word,
                    article=article,
                    defaults={"order": i},
                )


def set_article_identifiers(article, identifiers):
    doi = identifiers.get('doi')
    ojs_id = identifiers.get('id')

    if doi:
        ident_models.Identifier.objects.get_or_create(
            id_type="doi",
            identifier=doi,
            article=article,
        )
    if ojs_id:
        ident_models.Identifier.objects.get_or_create(
            id_type="ojs_id",
            identifier=ojs_id,
            article=article,
        )


def create_submission_files(article_obj, article_soup):
    created_files = []
    file_soup = article_soup.findAll('submission_file')

    for submission_file in file_soup:
        ojs_id = submission_file.attrs.get('id')
        file = submission_file.find('file')
        embed = file.find('embed')

        import base64
        content = base64.b64decode(embed.text)
        content_file = ContentFile(content)
        content_file.name = common.get_text_or_none(submission_file, 'name')
        article_file = files.save_file_to_article(
            content_file,
            article_obj,
            article_obj.owner,
            label="Imported File",
        )
        models.OJSFile.objects.get_or_create(
            journal=article_obj.journal,
            ojs_id=ojs_id,
            defaults={
                'file': article_file,
            }
        )
        created_files.append(article_file)
    return created_files


def create_galleys(article_obj, publication_soup):
    galley_soup = publication_soup.findAll('article_galley')

    for galley in galley_soup:
        submission_file_ref = galley.find(
            'submission_file_ref',
        ).attrs.get('id')
        import_file = models.OJSFile.objects.filter(
            journal=article_obj.journal,
            ojs_id=submission_file_ref,
        ).first()
        label = common.get_text_or_none(galley, 'name')
        galley, c = core_models.Galley.objects.update_or_create(
            article=article_obj,
            file=import_file.file,
            label=label,
            type=GALLEY_TYPES.get(label, "other"),
        )
        if not c:
            galley.file = import_file.file
            galley.save()


def get_title(article):
    title = common.get_text_or_none(article, 'title')
    title = title.replace('<p>', '')
    title = title.replace('</p>', '')
    return title
