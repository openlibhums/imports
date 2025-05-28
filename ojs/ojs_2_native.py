from bs4 import BeautifulSoup
import base64

from django.utils.html import strip_tags
from django.core.files.base import ContentFile

from plugins.imports import common, models
from plugins.imports.ojs import importers
from plugins.imports import utils
from core import models as core_models, files
from journal import models as journal_models
from submission import models as submission_models
from utils import shared
from identifiers import models as ident_models


def import_users(xml_content, journal):
    users_soup = BeautifulSoup(xml_content, 'lxml')
    users = users_soup.findAll('author')
    accounts = []

    for user in users:
        email = common.get_text_or_none(user, 'email')
        if not email:
            continue
        email = email.lower().strip()

        try:
            country = core_models.Country.objects.get(
                code=common.get_text_or_none(user, 'country'),
            )
        except core_models.Country.DoesNotExist:
            country = None

        defaults = {
            'first_name': common.get_text_or_none(user, 'firstname'),
            'last_name': common.get_text_or_none(user, 'lastname'),
            'institution': common.get_text_or_none(user, 'affiliation'),
            'country': country,
            'biography': common.get_text_or_none(user, 'biography'),
            'is_active': True,
            'email': email,
        }

        account, created = core_models.Account.objects.update_or_create(
            username=email,
            defaults=defaults,
        )

        if created:
            print(f'Account with email {email} created.')
            account.set_password(shared.generate_password(password_length=20))
            account.save()
        else:
            print(f'Account with email {email} updated.')

        accounts.append(account)

    return accounts


def import_issue(issue_soup, journal):
    volume_number = common.get_text_or_none(issue_soup, 'volume')
    issue_number = common.get_text_or_none(issue_soup, 'number')
    year = common.get_text_or_none(issue_soup, 'year')
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
    )

    if created:
        print(f'Created new issue: {issue.display_title}')
    else:
        print(f'Updated issue: {issue.display_title}')

    return issue


def import_issues(xml_content, journal, owner, stage):
    souped_xml = BeautifulSoup(xml_content, 'lxml')
    issue_soup = souped_xml.findAll('issue')

    for issue in issue_soup:
        article_soup = issue.findAll('article')
        issue = import_issue(issue, journal)
        articles_imported, articles_updated = import_articles(
            article_soup,
            journal,
            owner,
            stage,
            issue,
        )
        return articles_imported, articles_updated


def import_articles(article_soup, journal, owner, stage, issue):
    articles_imported = []
    articles_updated = []

    for article in article_soup:
        article_dict = {
            'title': common.get_text_or_none(article, 'title'),
            'abstract': common.get_text_or_none(article, 'abstract'),
            'date_published': utils.get_aware_datetime(
                common.get_text_or_none(article, 'date_published')
            ),
            'section': get_section(article, journal),
        }

        identifiers = get_identifiers(article)
        article_obj = get_article(identifiers, journal)

        if article_obj:
            submission_models.Article.objects.filter(
                pk=article_obj.pk,
            ).update(**article_dict)
            articles_updated.append(article_obj)
        else:
            article_obj = submission_models.Article.objects.create(
                journal=journal,
                owner=owner,
                **article_dict,
                stage=stage,
                is_import=True,
            )
            articles_imported.append(article_obj)

        set_article_issue(article_obj, issue)
        set_article_identifiers(article_obj, identifiers)
        create_galleys(article_obj, article)

    return articles_imported, articles_updated


def create_galleys(article_obj, article_soup):
    galley_soup = article_soup.findAll('galley')

    for galley in galley_soup:
        label = common.get_text_or_none(galley, 'label')
        file_node = galley.find('file')
        embed_node = file_node.find('embed') if file_node else None

        if embed_node:
            file_content = base64.b64decode(embed_node.text)
            file_name = embed_node.attrs.get('filename')
            mime_type = embed_node.attrs.get('mime_type')

            content_file = ContentFile(file_content, name=file_name)
            article_file = files.save_file_to_article(
                content_file,
                article_obj,
                article_obj.owner,
                label=label,
            )

            core_models.Galley.objects.update_or_create(
                article=article_obj,
                file=article_file,
                label=label,
                type=mime_type,
            )


def get_section(article_soup, journal):
    title = common.get_text_or_none(article_soup, 'title')
    section, created = submission_models.Section.objects.get_or_create(
        journal=journal,
        name=title,
    )
    return section


def get_identifiers(article_soup):
    doi = common.get_text_or_none(article_soup, 'doi')
    return {'doi': doi} if doi else {}


def get_article(identifiers, journal):
    doi = identifiers.get('doi')
    article = None
    if doi:
        article = submission_models.Article.get_article(journal, 'doi', doi)
    return article


def set_article_issue(article, issue):
    issue.articles.add(article)
    article.primary_issue = issue
    article.save()


def set_article_identifiers(article, identifiers):
    doi = identifiers.get('doi')
    if doi:
        ident_models.Identifier.objects.get_or_create(
            id_type='doi',
            identifier=doi,
            article=article,
        )
