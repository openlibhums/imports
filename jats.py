"""
Set of functions for importing articles from JATS XML
"""
import datetime
import hashlib
import mimetypes
import os
import tempfile
import uuid
import zipfile

from bs4 import BeautifulSoup
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from core import files
from core.models import Account
from identifiers.models import Identifier
from journal import models as journal_models
from production.logic import save_galley, save_galley_image
from plugins.imports.utils import DummyRequest
from submission import models as submission_models


def import_jats_article(
        jats_contents, journal,
        persist=True, filename=None, owner=None,
        images=None, request=None
):
    """ JATS import entrypoint
    :param jats_contents: (str) the JATS XML to be imported
    :param journal: Journal in which to import the article
    """
    jats_soup = BeautifulSoup((jats_contents), 'lxml')
    metadata_soup = jats_soup.find("article-meta")
    if not owner:
        owner = Account.objects.get(pk=1)

    # Gather metadata
    meta = {}
    meta["title"] = get_jats_title(metadata_soup)
    meta["abstract"] = get_jats_abstract(metadata_soup)
    meta["issue"], meta["volume"] = get_jats_issue(jats_soup)
    meta["keywords"] = get_jats_keywords(metadata_soup)
    meta["section_name"] = get_jats_section_name(jats_soup)
    meta["date_published"] = get_jats_pub_date(jats_soup) or datetime.date.today()
    meta["authors"] = []
    meta["date_submitted"] = None
    meta["date_accepted"] = None
    history_soup = metadata_soup.find("history")

    if history_soup:
        meta["date_submitted"] = get_jats_sub_date(history_soup)
        meta["date_accepted"] = get_jats_acc_date(history_soup)

    authors_soup = metadata_soup.find("contrib-group")
    author_notes = metadata_soup.find("author_notes")
    if authors_soup:
        meta["authors"] = get_jats_authors(authors_soup, author_notes)

    meta["identifiers"] = get_jats_identifiers(metadata_soup)

    if not persist:
        return meta
    else:
        # Persist Article
        article = save_article(journal, meta, owner=owner)
        # Save Galleys
        xml_file = ContentFile(jats_contents.encode("utf-8"))
        xml_file.name = filename or uuid.uuid4()
        request = request or DummyRequest(owner)
        galley = save_galley(article, request, xml_file, True, "XML")

    if images:
        load_jats_images(images, galley, request)
    return article


def import_jats_zipped(zip_file, journal, owner=None, persist=True):
    """ Import a batch of Zipped JATS articles and their figures
    :param zip_file: The zipped jats to be imported
    :param journal: Journal in which to import the articles
    :param owner: An instance of core.models.Account
    """
    articles = []
    jats_files_info = []
    image_map = {}
    temp_path = os.path.join(settings.BASE_DIR, 'files/temp')
    with zipfile.ZipFile(zip_file, 'r') as zf:
        with tempfile.TemporaryDirectory(dir=temp_path) as temp_dir:
            zf.extractall(path=temp_dir)

            for root, path, filenames in os.walk(temp_dir):
                jats_path = None
                jats_filename = None
                supplements = []

                for filename in filenames:
                    mimetype, _ = mimetypes.guess_type(filename)
                    file_path = os.path.join(root, filename)
                    if mimetype in files.XML_MIMETYPES:
                        jats_path = file_path
                        jats_filename = filename
                    else:
                        supplements.append(file_path)

                if jats_path:
                    with open(jats_path, 'r') as jats_file:
                        articles.append(import_jats_article(
                            jats_file.read(), journal, persist,
                            jats_filename, owner, supplements,
                        ))

    return articles



def get_jats_title(soup):
    title = soup.find("article-title")
    if title:
        return title.text
    else:
        return ""


def get_jats_abstract(soup):
    abstract = soup.find("abstract")
    if abstract:
        return abstract.text
    else:
        return ""


def get_jats_issue(soup):
    issue = soup.find("issue")
    issue = issue.text if issue else 0

    volume = soup.find("volume")
    volume = volume.text if volume else 0

    return (int(issue), int(volume))


def get_jats_pub_date(soup):
    pub_date_soup = soup.find("pub-date")
    if pub_date_soup:
        day = pub_date_soup.find("day")
        day = day.text if day else 1

        month = pub_date_soup.find("month")
        month = month.text if month else 1

        year = pub_date_soup.find("year").text

        return datetime.date(day=int(day), month=int(month), year=int(year))
    else:
        return None


def get_jats_sub_date(soup):
    sub_date_soup = soup.find("date", {"date-type": "received"})
    if sub_date_soup:
        day = sub_date_soup.find("day")
        day = day.text if day else 1

        month = sub_date_soup.find("month")
        month = month.text if month else 1

        year = sub_date_soup.find("year").text

        return datetime.date(day=int(day), month=int(month), year=int(year))
    else:
        return None


def get_jats_acc_date(soup):
    acc_date_soup = soup.find("date", {"date-type": "accepted"})
    if acc_date_soup:
        day = acc_date_soup.find("day")
        day = day.text if day else 1

        month = acc_date_soup.find("month")
        month = month.text if month else 1

        year = acc_date_soup.find("year").text

        return datetime.date(day=int(day), month=int(month), year=int(year))
    else:
        return None


def get_jats_keywords(soup):
    jats_keywords_soup = soup.find("kwd-group")
    if jats_keywords_soup:
        return {
            keyword.text
            for keyword in jats_keywords_soup.find_all("kwd")
        }
    else:
        return set()


def get_jats_section_name(soup):
    return soup.find("article").attrs.get("article-type")


def get_jats_authors(soup, author_notes=None):
    authors = []
    for author in soup.find_all("contrib", {"contrib-type": "author"}):
        institution = None
        if author.find("aff"):
            institution = author.find("aff").text
        if author.find("surname"):
            email_jats = author.find("email")
            if email_jats:
                email = email_jats.text
            else:
                email = default_email(author)
            author_data = {
                "first_name": author.find("given-names").text,
                "last_name": author.find("surname").text,
                "email": email,
                "correspondence": False,
                "institution": institution,
            }
            if author.attrs.get("corresp") == "yes" and author_notes:
                author_data["correspondence"] = True
                corresp_email = author_notes.find("email")
                if corresp_email:
                    author_data["email"] = corresp_email.text
            authors.append(author_data)
    return authors


def save_article(journal, metadata, issue=None, owner=None):
    with transaction.atomic():
        section, _ = submission_models.Section.objects \
            .language(settings.LANGUAGE_CODE).get_or_create(
                journal=journal,
                name=metadata["section_name"],
        )
        section.save()

        article = submission_models.Article.objects.create(
            journal=journal,
            title=metadata["title"],
            abstract=metadata["abstract"],
            date_published=metadata["date_published"],
            date_accepted=metadata["date_submitted"],
            date_submitted=metadata["date_submitted"],
            stage=submission_models.STAGE_PUBLISHED,
            is_import=True,
            owner=owner,
        )
        article.section = section
        article.save()

        if metadata["identifiers"]["doi"]:
            Identifier.objects.get_or_create(
                id_type="doi",
                identifier=metadata["identifiers"]["doi"],
                defaults={"article": article},
            )
        if metadata["identifiers"]["pubid"]:
            Identifier.objects.get_or_create(
                id_type="pubid",
                identifier=metadata["identifiers"]["pubid"],
                defaults={"article": article},
            )
        if metadata["identifiers"]["handle"]:
            Identifier.objects.get_or_create(
                id_type="handle",
                identifier=metadata["identifiers"]["handle"],
                defaults={"article": article},
            )
        for idx, author in enumerate(metadata["authors"]):
            account, _ = Account.objects.get_or_create(
                email=author["email"],
                defaults={
                    "first_name": author["first_name"],
                    "last_name": author["last_name"],
                    "institution": author["institution"] or journal.name,
                }
            )
            article.authors.add(account)
            author_order, created = submission_models.ArticleAuthorOrder \
                .objects.get_or_create(article=article, author=account)
            if created:
                author_order.order = idx
                author_order.save()

            if author["correspondence"]:
                article.correspondence_author = account
            article.save()
        article.snapshot_authors(article)

        for kwd in metadata["keywords"]:
            keyword, _ = submission_models.Keyword.objects.get_or_create(word=kwd)
            article.keywords.add(keyword)

        if not issue:
            issue_type = journal_models.IssueType.objects.get(
                code="issue",
                journal=journal,
            )
            issue, _ = journal_models.Issue.objects.get_or_create(
                volume=metadata["volume"],
                issue=metadata["issue"],
                journal=journal,
                defaults={"issue_type": issue_type}
            )
        issue.articles.add(article)
        article.primary_issue = issue
        article.save()

        return article


def get_jats_identifiers(soup):
    ids = {
        "pubid": None,
        "doi": None,
        "handle": None,
    }
    for article_id in soup.find_all("article-id"):
        if article_id.attrs.get("pub-id-type") == "doi":
            ids["doi"] = article_id.text
        elif article_id.attrs.get("pub-id-type") == "publisher-id":
            ids["pubid"] = article_id.text
        elif article_id.attrs.get("pub-id-type") == "handle":
            ids["handle"] = article_id.text


    return ids


def default_email(seed):
    hashed = hashlib.md5(str(seed).encode("utf-8")).hexdigest()
    return "{0}{1}".format(hashed, settings.DUMMY_EMAIL_DOMAIN)


def load_jats_images(images, galley, request):
    for img_path in images:
        _, filename = os.path.split(img_path)
        missing_images = galley.has_missing_image_files()
        all_images = galley.all_images()
        if filename in all_images:
            with open(img_path, 'rb') as image:
                content_file = ContentFile(image.read())
                content_file.name = filename

                if filename in missing_images:
                    save_galley_image(galley, request, content_file)
                else:
                    to_replace = galley.images.get(original_filename=filename)
                    files.overwrite_file(
                        content_file, to_replace,
                        ('articles', galley.article.pk)
                    )
