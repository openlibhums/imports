"""
An import procedure written for the export of InTransition from mediacommons
owner, Available from: https://github.com/NYULibraries/intransition
"""
import datetime
import uuid

from core import files, models as core_models
from dateutil import parser as dateparser
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.utils import timezone
from identifiers import models as id_models
from journal import models as journal_models
from review import models as rw_models
from submission import models as sm_models
from utils.logger import get_logger

from plugins.imports import common


logger = get_logger(__name__)


def import_article(journal, owner, data):
    pub_id = data["id"]
    article, created = update_or_create_article_by_id(journal, pub_id, data)
    article.owner = owner
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

        issue.articles.add(article)
        if not issue.date:
            issue.date = article.date_published
            issue.save()
        if i == 0:
            article.primary_issue = issue
            article.save()
        for idx, editor_data in enumerate(issue_data["editors"], 1):
            user = update_or_create_account(editor_data)
            journal_models.IssueEditor.objects.get_or_create(
                account=user,
                issue=issue,
                role="Editor",
                sequence=idx,
            )
        for idx, editor_data in enumerate(issue_data["coeditors"], 1):
            user = update_or_create_account(editor_data)
            journal_models.IssueEditor.objects.get_or_create(
                account=user,
                issue=issue,
                role="Co-editor",
                sequence=idx,
            )

    for review_data in data["reviews"]:
        import_review_data(article, review_data)

    for idx, author_data in enumerate(data["contributors"], 1):
        import_author(article, author_data, idx)
    article.snapshot_authors(article)

    make_xml_galley(article, owner, data)
    common.create_article_workflow_log(article)


def update_or_create_article_by_id(journal, pub_id, data):
    article = None
    created = False
    try:
        identifier = id_models.Identifier.objects.get(
            id_type="mediacommons",
            identifier=pub_id,
        )
        article = identifier.article
    except id_models.Identifier.DoesNotExist:
        pass

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

    section = sm_models.Section.objects.filter(journal=journal).first()
    for tag in data["tags"] or []:
        keyword, c = sm_models.Keyword.objects.get_or_create(word=tag)
        article.keywords.add(keyword)

    article.title = data["title"]
    article.section = section
    article.stage = "Published"
    article.date_published = dateparser.parse(data["date"])
    article.save()
    return article, created


def update_or_create_issue(journal, data):
    volume, number, year = parse_issue_parts_from_title(data["title"])
    # We only have the issue year
    pub_date = datetime.datetime(int(year), 1, 2)
    issue_type = journal_models.IssueType.objects.get(
        code="issue", journal=journal)
    issue, created = journal_models.Issue.objects.update_or_create(
        journal=journal,
        issue=number,
        volume=volume,
        defaults={
            "date": pub_date,
            "issue_title": data["title"],
            "issue_type": issue_type
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
    website = data["url"]["url"] if data["url"] else None
    acc, c = core_models.Account.objects.update_or_create(
        email=data["mail"],
        defaults = dict(
            institution=data["organization"],
            department=data["title"],
            website=website,
            first_name=first_name,
            middle_name=" ".join(middle_names) or None,
            last_name=last_name,
            enable_public_profile=True,
        ),
    )
    return acc

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

    context = {
        "video_url": data["embed"][0] if data["embed"] else None,
        "reviews": data["reviews"],
        "body": data["body"]
    }
    jats_body = render_to_string("import/mediacommons/article.xml", context)
    jats_context = {
        "include_declaration": True,
        "body": jats_body,
        "article": article,
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

