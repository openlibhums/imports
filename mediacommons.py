"""
An import procedure written for the export of InTransition from mediacommons
owner, Available from: https://github.com/NYULibraries/intransition
"""
import datetime
import os
from os.path import basename
import uuid

from core import (
        files,
        logic as core_logic,
        models as core_models,
)
from dateutil import parser as dateparser
from django.conf import settings
from django.core.files.base import ContentFile
from django.db.utils import IntegrityError
from django.template.loader import render_to_string
from django.utils import timezone
from lxml import etree
from identifiers import models as id_models
from journal import models as journal_models
import requests
from review import models as rw_models
from submission import models as sm_models
from utils.logger import get_logger

from plugins.imports import common
from plugins.imports.utils import DummyRequest


logger = get_logger(__name__)

HTML_TO_JATS_XSLT = os.path.join(
    settings.BASE_DIR,
    'plugins/imports/xslt/html-to-jats-1.2.xsl'
)

def import_article_xml(journal, owner,data):
    pub_id = data["id"]
    article = get_article_by_id(journal, pub_id)
    make_xml_galley(article, owner, data)


def import_article(journal, owner, data):
    pub_id = data["id"]
    article, created = update_or_create_article_by_id(
        journal, owner, pub_id, data)
    if created:
        logger.info("Created record for ID %s", pub_id)
    else:
        logger.info("Updating record for ID %s", pub_id)

    issues_data = data["part_of"]
    for i, issue_data in enumerate(issues_data):
        issue, created = update_or_create_issue(journal, issue_data)
        if created:
            logger.info("Created issue %s", issue)
        else:
            logger.info("Updated issue %s", issue)

        try:
            issue.articles.add(article)
        except IntegrityError:
            pass

        ordering, _ = journal_models.ArticleOrdering.objects.update_or_create(
            issue=issue,
            article=article,
            section=article.section,
            defaults={
                "order": data["article_order_within"]
            }
        )

        if not issue.date:
            issue.date = article.date_published
            issue.save()
        if i == 0:
            article.primary_issue = issue
            article.save()
        for idx, editor_data in enumerate(issue_data["coeditors"], 1):
            user = update_or_create_account(editor_data)
            journal_models.IssueEditor.objects.get_or_create(
                account=user,
                issue=issue,
                defaults=dict(
                    role="Co-editor",
                    sequence=idx,
                )
            )
        for idx, editor_data in enumerate(issue_data["editors"], 1):
            user = update_or_create_account(editor_data)
            journal_models.IssueEditor.objects.get_or_create(
                account=user,
                issue=issue,
                defaults=dict(
                    role="Editor",
                    sequence=idx,
                )
            )

    for review_data in data["reviews"]:
        import_review_data(article, review_data)

    for idx, author_data in enumerate(data["contributors"], 1):
        import_author(article, author_data, idx)
    article.snapshot_authors(article)

    make_xml_galley(article, owner, data)
    common.create_article_workflow_log(article)


def get_article_by_id(journal, pub_id):
    article = None
    try:
        identifier = id_models.Identifier.objects.get(
            id_type="mediacommons",
            identifier=pub_id,
            article__journal=journal,
        )
        article = identifier.article
    except id_models.Identifier.DoesNotExist:
        return None
    return article

def update_or_create_article_by_id(journal, owner, pub_id, data):
    created = False
    article = get_article_by_id(journal, pub_id)

    if not article:
        article = sm_models.Article.objects.create(
            journal=journal,
        )
        created = True
        identifier, c = id_models.Identifier.objects.get_or_create(
            id_type="mediacommons",
            identifier=pub_id,
            defaults={"article": article},
        )

    identifier, c = id_models.Identifier.objects.update_or_create(
        id_type="mediacommons_url",
        identifier=data["article_path"],
        defaults={"article": article},
    )

    section = sm_models.Section.objects.filter(journal=journal).first()
    for tag in data["tags"] or []:
        keyword, c = sm_models.Keyword.objects.get_or_create(word=tag)
        article.keywords.add(keyword)

    article.title = data["title"]
    article.section = section
    article.stage = "Published"
    article.date_published = dateparser.parse(data["date"])
    article.owner = owner
    article.peer_reviewed = bool(data.get("reviews", False))
    if data["representative_image"]:
        content_file = fetch_remote_file(data["representative_image"])
        request = DummyRequest(user=owner, journal=journal)
        core_logic.handle_article_thumb_image_file(
            content_file, article, request)
    article.save()
    return article, created


def update_or_create_issue(journal, data):
    volume, number, year = parse_issue_parts_from_title(data["title"])
    # We only have the issue year
    pub_date = datetime.datetime(int(year), 1, 2)
    issue_type = journal_models.IssueType.objects.get(
        code="issue", journal=journal)
    large_image = None
    if data["representative_image"]:
        large_image = fetch_remote_file(data["representative_image"])
    issue, created = journal_models.Issue.objects.update_or_create(
        journal=journal,
        issue=number,
        volume=volume,
        defaults={
            "date": pub_date,
            "issue_title": data["title"],
            "issue_type": issue_type,
            "large_image": large_image,
            "issue_description": data["body"],
        },
    )

    return issue, created


def parse_issue_parts_from_title(issue_title):
    """ Given an issue title, it parses it into issue identifier parts
    e.g.: Journal of Videographic Film & Moving Image Studies, 3.1, 2016
          ---------------------------------------------------  - -  ----
                                A                              B C   D
    A: Journal Title
    B: Issue Number
    C: Volume Number
    D: Year
    """
    _, issue_volume, year = issue_title.split(",")
    issue, volume = issue_volume.split(".")
    return issue, volume, int(year)


def update_or_create_account(data):
    try:
        first_name, *middle_names, last_name = data["name"].split(" ")
    except (AttributeError, TypeError):
        if data["name"] is None:
            first_name = ""
            middle_names = []
            last_name = data["mail"]
        else:
            raise
    website = data["url"]["url"] if data["url"] else None
    pic_file = None
    if data["picture"]:
        pic_file = fetch_remote_file(data["picture"])
    account, c = core_models.Account.objects.update_or_create(
        email=data["mail"],
        defaults = dict(
            institution=data["organization"],
            department=data["title"],
            website=website,
            first_name=first_name,
            middle_name=" ".join(middle_names) or None,
            last_name=last_name,
            enable_public_profile=True,
            profile_image=pic_file,
            biography=data.get("biography") or None,
        ),
    )
    return account

def import_review_data(article, review_data):
    review_round, _ = rw_models.ReviewRound.objects.get_or_create(
        article=article,
        round_number=1
    )
    review_form = rw_models.ReviewForm.objects.filter(
        journal=article.journal,
    ).first()
    if not review_data["reviewers"]:
        return
    reviewer = update_or_create_account(review_data["reviewers"][-1])
    reviewer.add_account_role("reviewer", article.journal)
    reviewer.add_account_role("author", article.journal)
    review_assignment, _ = rw_models.ReviewAssignment.objects.update_or_create(
        article=article,
        review_round=review_round,
        reviewer=reviewer,
        defaults=dict(
            review_type="traditional",
            decision="accept",
            visibility="open",
            date_requested=timezone.now(),
            date_due=timezone.now(),
            date_complete=timezone.now(),
            is_complete=True,
            for_author_consumption=True,
            permission_to_make_public=True,
            access_code=uuid.uuid4(),
            form=review_form,
        ),
    )
    element = review_form.elements.filter(name="Review").first()
    if element:
        answer, _ = rw_models.ReviewAssignmentAnswer.objects.get_or_create(
            assignment=review_assignment,
        )
        element.snapshot(answer)
        answer.answer = review_data["body"]
        answer.for_author_consumption = True
        answer.save()


def import_author(article, author_data, idx):
        author = update_or_create_account(author_data)
        author.add_account_role("author", article.journal)
        article.authors.add(author)
        order, c = sm_models.ArticleAuthorOrder.objects.update_or_create(
            article=article, author=author,
            defaults={"order": idx}
        )

def make_xml_galley(article, owner, data):
    for galley in article.galley_set.all():
        galley.unlink_files()
        galley.file.delete()
        galley.images.all().delete()
        galley.delete()

    body_as_jats = html_to_jats(data["body"])
    for review in data["reviews"]:
        # JATSify HTML review body
        review["body"] = html_to_jats(review["body"])
    context = {
        "embeds": [e for e in data["embed"]] if data["embed"] else None,
        "reviews": data["reviews"],
        "body": body_as_jats,
    }

    jats_body = render_to_string("import/mediacommons/article.xml", context)

    jats_context = {
        "include_declaration": True,
        "body": jats_body, "article": article,
    }
    jats = render_to_string("encoding/article_jats_1_2.xml", jats_context)

    django_file = ContentFile(jats.encode("utf-8"))
    django_file.name = "article.xml"
    jw_file = files.save_file_to_article(
        django_file, article, owner, label="XML", is_galley=True,
    )
    galley = core_models.Galley.objects.create(
        article=article,
        type="xml",
        label = "XML",
        file = jw_file,
    )
    article.galley_set.add(galley)


def fetch_remote_file(url, filename=None):
    logger.info("Fetching file from %s", url)
    response = requests.get(url)
    if not response.ok:
        logger.error("Status %s received", response.status_code)
        return None
    blob = response.content
    content_file = ContentFile(blob)
    if not filename:
        filename = common.get_filename_from_headers(response)
    if not filename:
        filename = basename(url)
    content_file.name = filename
    return content_file


def html_to_jats(html_string):
    """Transforms incoming html string into JATS"""
    html_tree = etree.HTML(html_string)

    # Prepare XSLT
    xml_parser = etree.XMLParser()
    xslt_tree = etree.parse(HTML_TO_JATS_XSLT, xml_parser)
    xsl_transform = etree.XSLT(xslt_tree)

    # Perform transformation
    jats_xml_tree = xsl_transform(html_tree)
    return str(jats_xml_tree)

def extract_images(galley, body):
    pass

