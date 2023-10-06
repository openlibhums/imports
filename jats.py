"""
Set of functions for importing articles from JATS XML
"""
import datetime
import hashlib
import mimetypes
import os
import tempfile
import traceback
import uuid
import zipfile

from bs4 import BeautifulSoup
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from core import files
from core import models as core_models
from core.models import Account
from identifiers.models import Identifier
from journal import models as journal_models
from production.logic import save_galley, save_galley_image
from submission import models as submission_models
from utils import install
from utils.logger import get_logger

from plugins.imports import common
from plugins.imports.utils import DummyRequest

logger = get_logger(__name__)


def import_jats_article(
        jats_contents, journal=None,
        persist=True, filename=None, owner=None,
        images=None, request=None, stage=None,
):
    """ JATS import entrypoint
    :param jats_contents: (str) the JATS XML to be imported
    :param journal: Journal in which to import the article
    """
    jats_soup = BeautifulSoup((jats_contents), 'lxml')
    metadata_soup = jats_soup.find("article-meta")
    if not metadata_soup:
        err = ValueError("Invalid JATS-XML or no <article-meta> found")
        logger.exception(err)
        raise err
    if not owner:
        owner = Account.objects.get(pk=1)

    # Gather metadata
    meta = {}
    meta["journal"] = get_jats_journal_metadata(jats_soup)
    meta["title"] = get_jats_title(metadata_soup)
    meta["abstract"] = get_jats_abstract(metadata_soup)
    meta["issue"], meta["volume"] = get_jats_issue(jats_soup)
    meta["keywords"] = get_jats_keywords(metadata_soup)
    meta["section_name"] = get_jats_section_name(jats_soup)
    meta["date_published"] = get_jats_pub_date(jats_soup) or datetime.date.today()
    meta["license_url"], meta["license_text"] = get_jats_license(jats_soup)
    meta["rights"] = get_jats_rights_statement(jats_soup)
    meta["authors"] = []
    meta["date_submitted"] = None
    meta["date_accepted"] = None
    try:
        meta["first_page"] = int(metadata_soup.find("fpage").text)
    except (ValueError, AttributeError):
        meta["first_page"] = None
    try:
        meta["last_page"] = int(metadata_soup.find("lpage").text)
    except (ValueError, AttributeError):
        meta["last_page"] = None
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
        article = save_article(meta, journal, owner=owner, stage=stage)
        # Save Galleys
        for galley in article.galley_set.all():
            galley.delete()
        if not isinstance(jats_contents, bytes):
            jats_contents = jats_contents.encode("utf-8")
        xml_file = ContentFile(jats_contents)
        xml_file.name = filename or uuid.uuid4()
        request = request or DummyRequest(owner)
        galley = save_galley(article, request, xml_file, True, "XML")

    if images:
        load_jats_images(images, galley, request)
    return article


def import_jats_zipped(zip_file, journal=None, owner=None, persist=True, stage=None):
    """ Import a batch of Zipped JATS articles and their associated files
    :param zip_file: The zipped jats to be imported
    :param journal: Journal in which to import the articles
    :param owner: An instance of core.models.Account
    """
    errors = []
    articles = []
    jats_files_info = []
    image_map = {}
    temp_path = os.path.join(settings.BASE_DIR, 'files/temp')
    with zipfile.ZipFile(zip_file, 'r') as zf:
        with tempfile.TemporaryDirectory(dir=temp_path) as temp_dir:
            zf.extractall(path=temp_dir)

            for root, path, filenames in os.walk(temp_dir):
                try:
                    jats_path = jats_filename = pdf_path = pdf_filename = None
                    supplements = []

                    for filename in filenames:
                        mimetype, _ = mimetypes.guess_type(filename)
                        file_path = os.path.join(root, filename)
                        if mimetype in files.XML_MIMETYPES:
                            jats_path = file_path
                            jats_filename = filename
                        elif mimetype in files.PDF_MIMETYPES:
                            pdf_path = file_path
                            pdf_filename = filename
                        else:
                            supplements.append(file_path)

                    if jats_path:
                        logger.info("[JATS] Importing from %s", jats_path)
                        with open(jats_path, 'r') as jats_file:
                            article = import_jats_article(
                                jats_file.read(), journal, persist,
                                jats_filename, owner, supplements,
                                stage=stage,
                            )
                            articles.append((jats_filename, article))
                        if pdf_path:
                            import_pdf(article, pdf_path, pdf_filename)
                except Exception as err:
                    logger.warning(err)
                    logger.warning(traceback.format_exc())
                    errors.append((filenames, err))

    return articles, errors


def get_jats_journal_metadata(soup):
    journal_metadata = {}
    journal_soup = soup.find("journal-meta")
    if journal_soup:
        # Journal code
        id_soup = journal_soup.find(
            "journal-id", {"journal-id-type": "publisher-id"})
        if id_soup:
            journal_metadata["code"] = id_soup.text
        else:
            abbrev_soup = journal_soup.find("abbrev-journal-title")
            if abbrev_soup:
                journal_metadata["code"] = abbrev_soup.text

        # Journal title
        title_soup = journal_soup.find("journal-title")
        if title_soup:
            journal_metadata["title"] = title_soup.text
        issn_soup = journal_soup.find("issn")
        if issn_soup:
            journal_metadata["issn"] = issn_soup.text
    return journal_metadata


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

        # in some cases the aff may be outside <contrib> in this case
        # we can look for something like:
        # <xref ref-type="aff" rid="aff1">1</xref>

        if not institution:
            aff_xref = author.find('xref', {'ref-type': 'aff'})
            if aff_xref:
                aff_id = aff_xref.get('rid')
                if aff_id:
                    aff = soup.find('aff', {'id': aff_id})
                    if aff:
                        try:
                            aff.find('label').decompose()
                        except AttributeError:
                            pass
                        institution = aff.text.strip()

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


def get_article(id_soup, journal):
    article = None

    if id_soup.get("doi"):
        try:
            article = Identifier.objects.get(
                id_type="doi",
                identifier=id_soup["doi"],
            ).article
            logger.info("Matched article by DOI: %s", article)
        except Identifier.DoesNotExist:
            if id_soup.get("pubid"):
                try:
                    article = Identifier.objects.get(
                        id_type="pubid",
                        identifier=id_soup["pubid"],
                        article__journal=journal,
                    ).article
                    logger.info("Matched article by pubid: %s", article)
                except Identifier.DoesNotExist:
                    logger.info("No article matched")
        return article


def save_article(metadata, journal=None, issue=None, owner=None, stage=None):
    if not journal and metadata["journal"] and metadata["journal"].get("code"):
        journal = get_or_create_journal(metadata)
    elif not journal:
        journal = get_lost_found_journal()

    with transaction.atomic():
        section, _ = submission_models.Section.objects \
            .get_or_create(
                journal=journal,
                name=metadata["section_name"],
        )
        section.save()

        article = get_article(metadata.get("identifiers", {}), journal)
        if not article:
            article = submission_models.Article.objects.create(
                journal=journal,
                title=metadata["title"],
                abstract=metadata["abstract"],
                date_published=metadata["date_published"],
                date_accepted=metadata["date_submitted"],
                date_submitted=metadata["date_submitted"],
                rights=metadata["rights"],
                stage=stage or submission_models.STAGE_PUBLISHED,
                is_import=True,
                owner=owner,
                first_page=metadata["first_page"],
                last_page=metadata["last_page"]
            )
            article.section = section
            article.save()
            common.create_article_workflow_log(article)
        else:
            article.title = metadata["title"]
            article.abstract = metadata["abstract"]
            article.date_published = metadata["date_published"]
            article.date_published = metadata["date_published"]
            article.date_accepted = metadata["date_submitted"]
            article.date_submitted = metadata["date_submitted"]
            article.rights = metadata["rights"]
            article.first_page = metadata["first_page"]
            article.last_page = metadata["last_page"]
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
                article__journal=journal,
                defaults={"article": article},
            )
        if metadata["identifiers"]["handle"]:
            Identifier.objects.get_or_create(
                id_type="handle",
                identifier=metadata["identifiers"]["handle"],
                defaults={"article": article},
            )
        for idx, author in enumerate(metadata["authors"]):
            account, _ = Account.objects.update_or_create(
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

        if metadata["license_url"]:
            url = metadata["license_url"]
            try:
                lic = submission_models.Licence.objects.get(
                    url=url, journal=article.journal,
                )
            except submission_models.Licence.DoesNotExist:
                lic = submission_models.Licence.objects.create(
                    url=url,
                    journal=article.journal,
                    short_name=url[-14:],
                    name="Imported License",
                    text=metadata.get("license_text")
                )
            article.license = lic
            article.save()

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


def import_pdf(article, pdf_path, pdf_filename):
    owner = article.owner or Account.objects.get(pk=1)
    with open(pdf_path, "rb") as f:
        content_file = ContentFile(f.read())
        content_file.name = pdf_filename
        article_file = files.save_file_to_article(
            content_file, article, owner, label="PDF",
        )
        core_models.Galley.objects.get_or_create(
            article=article,
            type="pdf",
            defaults={
                "label": "PDF",
                "file": article_file,
            }
        )

def get_or_create_journal(metadata):
    # Try to get it with journal code
    code = metadata["journal"]["code"]
    created = None
    journal = journal_models.Journal.objects.filter(code__iexact=code).first()
    if not journal and metadata["journal"].get("issn"):
        # Try with ISSN
        setting = core_models.SettingValue.objects.filter(
            setting__name="journal_issn",
            value=metadata["journal"]["issn"],
        ).first()
        if setting:
            journal = setting.journal
    if not journal and metadata["journal"].get("title"):
        # Try with title
        setting = core_models.SettingValue.objects.filter(
            setting__name="journal_name",
            value = metadata["journal"]["title"],
        ).first()
        if setting:
            journal = setting.journal
    if not journal:
        # Create a new journal
        journal = journal_models.Journal.objects.create(code=code)

    if created:
        journal.title = metadata["journal"].get("title", code)
        journal.issn = metadata["journal"].get("issn") or "0000-0000"
        # This part is copied from press/views.py, should live in core
        install.update_issue_types(journal)
        journal.setup_directory()
    return journal

def get_lost_found_journal():
    journal, created = journal_models.Journal.objects.get_or_create(
        code="lost_found",
    )


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


def get_jats_license(soup):
    license_url = license_text = None
    license_soup = soup.find("license")
    if license_soup:
        license_url = license_soup.get("xlink:href")
        license_text = " ".join((
            license_p.text
            for license_p in license_soup.find_all("license-p")
        ))
    return license_url, license_text


def get_jats_rights_statement(soup):
    text = None
    rights_soup = soup.find("copyright-statement")
    if rights_soup:
        text = rights_soup.text
    return text


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
