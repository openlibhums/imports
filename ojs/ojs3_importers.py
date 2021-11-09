from datetime import timedelta

from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.management import call_command
from django.core.exceptions import ObjectDoesNotExist
from django.template.defaultfilters import linebreaksbr
from django.utils import timezone
from django.utils.html import strip_tags

from cms import models as cms_models
from copyediting import models as copyediting_models
from core import files as core_files
from core import logic as core_logic
from core import models as core_models
from identifiers import models as identifiers_models
from journal import models as journal_models
from review import models as review_models
from submission import models as sm_models
from utils.logger import get_logger
from utils import setting_handler

from plugins.imports import models

# Submission stages
STATUS_QUEUED = 1
STATUS_PUBLISHED = 3
STATUS_DECLINED = 4
STATUS_SCHEDULED = 5

#WORKFLOW STAGES
WORKFLOW_STAGE_ID_SUBMISSION = 1
WORKFLOW_STAGE_ID_INTERNAL_REVIEW = 2
WORKFLOW_STAGE_ID_EXTERNAL_REVIEW = 3
WORKFLOW_STAGE_ID_EDITING = 4
WORKFLOW_STAGE_ID_PRODUCTION = 5

WORKFLOW_STAGE_MAP = {
    WORKFLOW_STAGE_ID_SUBMISSION: {
        "stage": sm_models.STAGE_UNASSIGNED,
        "workflow": None,
    },
    WORKFLOW_STAGE_ID_INTERNAL_REVIEW: {
        "stage": sm_models.STAGE_UNDER_REVIEW,
        "workflow": sm_models.STAGE_UNASSIGNED,
    },
    WORKFLOW_STAGE_ID_EDITING: {
        "stage": sm_models.STAGE_EDITOR_COPYEDITING,
        "workflow": sm_models.STAGE_EDITOR_COPYEDITING,
    },
    WORKFLOW_STAGE_ID_PRODUCTION: {
        "stage": sm_models.STAGE_TYPESETTING,
        "workflow": sm_models.STAGE_TYPESETTING,

    },
}
# Alias internal and external review stages
WORKFLOW_STAGE_MAP[WORKFLOW_STAGE_ID_EXTERNAL_REVIEW] = WORKFLOW_STAGE_MAP[
        WORKFLOW_STAGE_ID_INTERNAL_REVIEW]

#R ole IDs
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

# review assignment statuses
REVIEW_ASSIGNMENT_STATUS_AWAITING_RESPONSE = 0 # request has been sent but reviewer has not responded
REVIEW_ASSIGNMENT_STATUS_DECLINED = 1 # reviewer declined review request
REVIEW_ASSIGNMENT_STATUS_RESPONSE_OVERDUE = 4 # review not responded within due date
REVIEW_ASSIGNMENT_STATUS_ACCEPTED = 5 # reviewer has agreed to the review
REVIEW_ASSIGNMENT_STATUS_REVIEW_OVERDUE = 6 # review not submitted within due date
REVIEW_ASSIGNMENT_STATUS_RECEIVED = 7 # review has been submitted
REVIEW_ASSIGNMENT_STATUS_COMPLETE = 8 # review has been confirmed by an editor
REVIEW_ASSIGNMENT_STATUS_THANKED = 9 # reviewer has been thanked
REVIEW_ASSIGNMENT_STATUS_CANCELLED = 10 # reviewer cancelled review request


# Review Recommendations
SUBMISSION_REVIEWER_RECOMMENDATION_ACCEPT = 1
SUBMISSION_REVIEWER_RECOMMENDATION_PENDING_REVISIONS = 2
SUBMISSION_REVIEWER_RECOMMENDATION_RESUBMIT_HERE = 3
SUBMISSION_REVIEWER_RECOMMENDATION_RESUBMIT_ELSEWHERE = 4
SUBMISSION_REVIEWER_RECOMMENDATION_DECLINE = 5
SUBMISSION_REVIEWER_RECOMMENDATION_SEE_COMMENTS = 6


REVIEW_RECOMMENDATION_MAP = {
    SUBMISSION_REVIEWER_RECOMMENDATION_ACCEPT: 'accept',
    SUBMISSION_REVIEWER_RECOMMENDATION_PENDING_REVISIONS: 'minor_revisions',
    SUBMISSION_REVIEWER_RECOMMENDATION_RESUBMIT_HERE: 'major_revisions',
    SUBMISSION_REVIEWER_RECOMMENDATION_RESUBMIT_ELSEWHERE: 'reject',
    SUBMISSION_REVIEWER_RECOMMENDATION_DECLINE: 'reject',
    SUBMISSION_REVIEWER_RECOMMENDATION_SEE_COMMENTS: 'minor_revisions',
}

REVIEW_ROUND_STATUS_REVISIONS_REQUESTED = 1
REVIEW_ROUND_STATUS_RESUBMIT_FOR_REVIEW = 2
REVIEW_ROUND_STATUS_SENT_TO_EXTERNAL = 3
REVIEW_ROUND_STATUS_ACCEPTED = 4
REVIEW_ROUND_STATUS_DECLINED = 5
REVIEW_ROUND_STATUS_REVISIONS_SUBMITTED = 11

REVISION_STATUSES = {2, 3, 11}


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


def import_article(client, journal, article_dict, editorial=False, galleys=True):
    pub_article_dict = get_pub_article_dict(article_dict, client)
    article_dict["publication"] = pub_article_dict
    article = import_article_metadata(article_dict, journal, client)
    if not article:
        return
    import_author_assignments(article, article_dict)
    if galleys:
        import_article_galleys(article, pub_article_dict, journal, client)
    if editorial:
        import_manuscripts(client, article, article_dict)
        import_editor_assignments(article, article_dict)
        if article_dict["reviewAssignments"] or article_dict["reviewRounds"]:
            import_reviews(client, article, article_dict)
        import_copyedits(client, article, article_dict)
        import_production(client, article, article_dict)
    set_stage(article, article_dict)


def import_author_assignments(article, article_dict):
    for i, author_id in enumerate(article_dict["authors"]):
        try:
            account = models.OJSAccount.objects.get(
                ojs_id=author_id, journal=article.journal).account
            article.authors.add(account)
            if i == 0:
                article.owner = account
                article.correspondence_author = account
                article.save()
        except models.OJSAccount.DoesNotExist:
            logger.error("Author does not exist %s", author_id)


def import_manuscripts(client, article, article_dict):
    files = client.get_manuscript_files(article_dict["id"])
    label = "Author Manuscript"
    for file_json in files:
        manuscript = import_file(file_json, client, article, label=label)
        if manuscript:
            article.manuscript_files.add(manuscript)


def import_editor_assignments(article, article_dict):
    for editor_id in set(article_dict["editors"]):
        account = models.OJSAccount.objects.get(
            ojs_id=editor_id, journal=article.journal).account
        review_models.EditorAssignment.objects.get_or_create(
            article=article,
            editor=account,
            defaults={
                "editor_type": "editor",
                "assigned": article.date_submitted,
            }
        )
    for editor_id in set(article_dict["section-editors"]):
        account = models.OJSAccount.objects.get(
            ojs_id=editor_id, journal=article.journal).account
        review_models.EditorAssignment.objects.get_or_create(
            article=article,
            editor=account,
            defaults={
                "editor_type": "section-editor",
                "assigned": article.date_submitted,
            }
        )

def import_issue(client, journal, issue_dict):
    issue, c = get_or_create_issue(issue_dict, journal)
    if c:
        logger.info("Created Issue %s from OJS ID %s", issue, issue_dict["id"])
    else:
        logger.info("Updating Issue %s from OJS ID %s", issue, issue_dict["id"])

    for section_dict in issue_dict["sections"]:
        section = import_section(section_dict, issue, client)

    for order, article_dict in enumerate(issue_dict["articles"]):
        logger.warning(article_dict["stageId"])
        article_dict["publication"] = get_pub_article_dict(article_dict, client)
        article, c = get_or_create_article(article_dict, journal)
        if article:
            article.primary_issue = issue
            if not article.date_published:
                article.date_published = issue.date
            article.save()
            if not article.section:
                logger.warning("No section for article %s" % article)
                article.section, _ = sm_models.Section.objects.get_or_create(
                    name="Article",
                    journal=article.journal
                )
                article.save()
            issue.articles.add(article)
            journal_models.ArticleOrdering.objects.update_or_create(
                section=article.section,
                issue=issue,
                article=article,
                defaults={"order": order}
            )
    if not issue.large_image and issue_dict["coverImageUrl"].values():
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
    if not article:
        return None
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
            dateparser.parse(
                article_dict["publication"]['datePublished']).replace(hour=12
            )
        )
        article.date_published = date_published
        article.stage = sm_models.STAGE_PUBLISHED
    license_url = article_dict["publication"]["licenseUrl"] or ''
    license_url = license_url.replace("http:", "https:")
    if license_url:
        article.license, _ = sm_models.Licence.objects.get_or_create(
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
                word, _ = sm_models.Keyword.objects.get_or_create(
                    word=keyword)
                sm_models.KeywordArticle.objects.update_or_create(
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


def import_reviews(client, article, article_dict):
    create_workflow_log(article, sm_models.STAGE_UNASSIGNED)
    logger.info("Importing peer reviews")
    default_form = review_models.ReviewForm.objects.get(
        slug="default-form", journal=article.journal)
    for round_dict in article_dict["reviewRounds"]:
        round, c = review_models.ReviewRound.objects.get_or_create(
            article=article,
            round_number=round_dict["round"],
        )
        import_review_round_files(client, article_dict["id"], round_dict["id"], round)
        import_revision(client, article_dict["id"], article, round_dict)

    for review_dict in article_dict["reviewAssignments"]:
        try:
            reviewer = models.OJSAccount.objects.get(
                ojs_id=review_dict["reviewerId"],
                journal=article.journal,
            ).account
        except models.OJSAccount.DoesNotExist:
            user_dict = client.get_user(review_dict["reviewerId"])
            reviewer = import_user(user_dict, article.journal)

        review_defaults = dict(
            review_type="traditional",
            visibility="double-blind",
            date_due=attempt_to_make_timezone_aware(review_dict["due"]),
            date_requested=attempt_to_make_timezone_aware(review_dict["dateAssigned"]),
            date_complete=attempt_to_make_timezone_aware(review_dict["dateCompleted"]),
            date_accepted=attempt_to_make_timezone_aware(review_dict["dateConfirmed"]),
            form=default_form,
        )

        assignment, _ = review_models.ReviewAssignment.objects.update_or_create(
            article=article,
            reviewer=reviewer,
            review_round=review_models.ReviewRound.objects.get(
                article=article,
                round_number=review_dict["round"],
            ),
            defaults=review_defaults,
        )
        if review_dict["statusId"] == REVIEW_ASSIGNMENT_STATUS_DECLINED:
            assignment.date_declined = assignment.date_confirme
            assignment.date_accepted = assignment.date_complete = None
            assignment.is_complete = True
        elif review_dict["statusId"] == REVIEW_ASSIGNMENT_STATUS_CANCELLED:
            assignment.decision = "withdrawn"

        if review_dict["recommendation"]:
            assignment.decision = REVIEW_RECOMMENDATION_MAP[
                review_dict["recommendation"]]
            assignment.is_complete = True
        assignment.save()

        import_reviewer_files(
            client, article_dict["id"], assignment, review_dict["id"]
        )
        if review_dict["comments"]:
            handle_review_comment(
                article, assignment, default_form, review_dict["comments"])

        assignment.comments_for_editor = review_dict["commentsEditor"]
        assignment.save()


def import_copyedits(client, article, article_dict):
    drafts = []
    draft_files = client.get_copyediting_files(article_dict["id"], drafts=True)
    draft_label = "Draft"
    for file_json in draft_files:
        draft = import_file(file_json, client, article, label=draft_label)
        article.manuscript_files.add(draft)
        drafts.append(draft)

    copyedited_files = client.get_copyediting_files(article_dict["id"])
    copyediting_models.CopyeditAssignment.objects.filter(article=article).delete()
    copyedits = []
    copyedit_label = "Copyedited Manuscript"
    for file_json in copyedited_files:
        copyedit = import_file(file_json, client, article, label=copyedit_label)
        if copyedit:
            assignment = copyediting_models.CopyeditAssignment.objects.create(
                article=article,
                copyeditor=copyedit.owner,
                notified=True,
                decision="accept",
                date_decided=copyedit.date_uploaded,
                copyeditor_completed=copyedit.date_modified or copyedit.date_uploaded
            )
            assignment.copyeditor_files.add(copyedit)
            assignment.files_for_copyediting.add(*drafts)
            assignment.save()
            copyedits.append(copyedit)

    if drafts or copyedits:
        create_workflow_log(article, sm_models.STAGE_EDITOR_COPYEDITING)


def import_production(client, article, article_dict):
    logger.info("Importing Production Ready files")
    files = client.get_prod_ready_files(article_dict["id"])
    prod_ready_files = []
    label = "Production Ready File"
    for file_json in files:
        prod_ready_file = import_file(file_json, client, article, label=label)
        if prod_ready_file:
            article.manuscript_files.add(prod_ready_file)
            prod_ready_files.append(prod_ready_file)

    if prod_ready_files:
        typesetting_plugin = article.journal.element_in_workflow(
            "Typesetting Plugin")
        if typesetting_plugin:
            stage = typesetting_settings.STAGE
            create_workflow_log( article, typesetting_settings.STAGE)
        else:
            create_workflow_log(article, sm_models.STAGE_TYPESETTING)

def import_revision(client, submission_id, article, round_dict):
    logger.info("Importing revision for round %s" % round_dict["round"])
    revision_files = []
    date_completed = None
    files = client.get_review_files(
        submission_id, round_ids=[round_dict["id"]], revisions=True)
    label = "Author Revision"
    for file_json in files:
        revision = import_file(file_json, client, article, label)
        if revision:
            revision_files.append(revision)
    if revision_files:
        date_completed = revision_files[-1].date_uploaded

    if revision_files or round_dict["statusId"] in {1, 2}:
        request, c  = review_models.RevisionRequest.objects.get_or_create(
            article=article,
            date_completed=date_completed,
            defaults={
                "editor_note": round_dict["status"],
                "editor": article.editor_list()[0],
                "date_due": timezone.now() + timedelta(7),
                "type": "major_revisions",
            }
        )
        for revision in revision_files:
            article.manuscript_files.add(revision)
            request.actions.update_or_create(
                text="Author Uploaded: %s" % revision.original_filename,
                defaults={
                    "logged": revision.date_uploaded,
                    "user": revision.owner or article.owner,
                }
            )


def import_review_round_files(client, submission_id, round_id, round):
    label = "File for Peer Review"
    files = client.get_review_files(submission_id, round_ids=[round_id])
    round.review_files.clear()
    for file_json in files:
        file_for_review = import_file(file_json, client, round.article, label)
        round.review_files.add(file_for_review)


def import_reviewer_files(client, submission_id, assignment, review_id):
    label = "File from Reviewer"
    files = client.get_review_files(submission_id, review_ids=[review_id])
    for file_json in files:
        reviewer_file = import_file(file_json, client, assignment.article, label)
        assignment.review_file = reviewer_file
        assignment.save()



def import_user(user_dict, journal):
    if len(user_dict["email"]) >= 48: return (None, None)
    account, created = core_models.Account.objects.get_or_create(
        email=user_dict["email"],
        defaults = {
            "first_name": delocalise(user_dict["givenName"]),
            "last_name": delocalise(user_dict["familyName"]),
        }
    )
    if created:
        logger.info("Imported new OJS3 user: %s", account)
    else:
        logger.info("Updating OJS3 user: %s", account)

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

    _, c = models.OJSAccount.objects.get_or_create(
        journal=journal,
        account=account,
        ojs_id=user_dict["id"],
    )
    if c:
        logger.debug(
            "Linked user %s with ojs id %s on %s",
            account, user_dict["id"], journal,
        )

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
    if not owner:
        if file_json["uploaderUserId"]:
            owner = models.OJSAccount.objects.get(
                ojs_id=file_json["uploaderUserId"],
                journal=article.journal
            ).account
        else:
            owner = article.owner

    django_file = client.fetch_file(file_json["url"])
    if django_file:
        janeway_file = core_files.save_file_to_article(
            django_file, article, owner, label=label or file_json["label"]
        )
        if file_json["mimetype"]:
            janeway_file.mime_type = file_json["mimetype"]
        if file_json["createdAt"]:
            janeway_file.date_uploaded = attempt_to_make_timezone_aware(
                file_json["createdAt"])

        janeway_file.original_filename = file_name
        janeway_file.save()

        if file_json["updatedAt"]:
            core_models.File.objects.filter(id=janeway_file.pk).update(
                date_modified=attempt_to_make_timezone_aware(file_json["updatedAt"])
            )
        elif file_json["createdAt"]:
            core_models.File.objects.filter(id=janeway_file.pk).update(
                date_modified=attempt_to_make_timezone_aware(file_json["createdAt"])
            )

        return janeway_file


def get_or_create_issue(issue_dict, journal):
    issue_type = journal_models.IssueType.objects.get(
        journal=journal, code='issue')
    date_published = attempt_to_make_timezone_aware(issue_dict['datePublished'])
    if date_published and issue_dict["year"]:
        # Year does not need to match pub date in OJS.
        # In Janeway, year is taken from date.year
        date_published = date_published.replace(year=issue_dict["year"])
    if not date_published:
        # Date published is required in Janeway, so set 10 years into the future
        date_published = timezone.now() + relativedelta(years=10)
    issue, c = journal_models.Issue.objects.update_or_create(
        volume=issue_dict.get("volume") or 0,
        issue=issue_dict.get("number") or "0",
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
    if not article_dict['dateSubmitted']:
        return None, created
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
        article = sm_models.Article(
            journal=journal,
            title=delocalise(
                article_dict["publication"]['fullTitle']
                or "NO TITLE"
            ),
            language=article_dict.get('locale'),
            stage=sm_models.STAGE_UNASSIGNED,
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
        section = sm_models.Section.objects.create(
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

    We create frozen records directly from the author data in OJS, since the
    same email address can be shared across multiple authors in OJS3. We then
    link the account to the frozen record if one exists for the given email
    :param author: an author object from OJS
    :param article: an instance of submission.models.Article
    """
    account = None
    frozen_dict = {
        'article': article,
        'first_name': delocalise(author["givenName"]),
        'last_name': delocalise(author["familyName"]),
        'institution': delocalise(author["affiliation"]) or '',
        'order': author["seq"],
    }
    frozen, created = sm_models.FrozenAuthor.objects.get_or_create(
        **frozen_dict)
    if created:
        logger.debug("Added Frozen Author %s", frozen_dict)
    else:
        logger.debug("Updated Frozen Author %s", frozen_dict)

    if author["email"]:
        try:
            account = core_models.Account.objects.get(
                email__iexact=author["email"])
            frozen.account = account
            frozen.save()
        except core_models.Account.DoesNotExist:
            logger.info("No account matching %s" % author["email"])
            frozen.frozen_email = author["email"]

    if author["orcid"]:
        if not account or not account.orcid:
            frozen.frozen_orcid = author["orcid"].rsplit("/")[-1]

    frozen.save()
    return frozen, created


def import_journal_metadata(client, journal_dict, update_journal_data=False):
    journal, created = get_or_create_journal(journal_dict)
    if journal_dict["printIssn"]:
        journal.print_issn = journal_dict["printIssn"]

    if update_journal_data or created:
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
        import_editorial_team(journal_dict, journal)

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
    created = False
    try:
        journal = journal_models.Journal.objects.get(code=code)
    except journal_models.Journal.DoesNotExist:
        name = delocalise(journal_dict["name"])
        default_domain = "localhost/%s" % code
        call_command(
            "install_journal",
            journal_code=code,
            journal_name=name,
            base_url=default_domain,
        )
        created = True
        journal = journal_models.Journal.objects.get(code=code)

    return journal, created


def import_editorial_team(journal_dict, journal):
    html = delocalise(journal_dict["editorialTeam"])
    if html:
        core_models.EditorialGroup.objects.update_or_create(
            name="Editorial Team",
            journal=journal,
            defaults={
                "description": html,
                "sequence": 0,
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


def handle_review_comment(article, review_obj, form, comment, public=True):
    element = form.elements.filter(kind="textarea").first()
    if element:
        soup = BeautifulSoup(comment, "html.parser")
        for tag in soup.find_all(["br", "p"]):
            tag.replace_with("\n" + tag.text)
        comment = soup.text
        answer, _ = review_models.ReviewAssignmentAnswer.objects.get_or_create(
            assignment=review_obj,
        )
        element.snapshot(answer)
        answer.answer = comment
        answer.for_author_consumption=public
        answer.save()
    else:
        comment = linebreaksbr(comment)
        filepath = core_files.create_temp_file(
            comment, 'comment-from-ojs.html')
        f = open(filepath, 'r')
        comment_file = core_files.save_file_to_article(
            f,
            article,
            article.owner,
            label='Review Comments',
            save=False,
        )

        review_obj.review_file = comment_file
    review_obj.save()

    return review_obj


def create_workflow_log(article, stage):
    element = core_models.WorkflowElement.objects.get(
        journal=article.journal,
        stage=stage,
    )

    return core_models.WorkflowLog.objects.get_or_create(
        article=article,
        element=element,
    )


def set_stage(article, article_dict):
    """ Calculates the Stage for the given article and sets it
    The article dict contains an attribute "status" that corresponds to one
    of the STATUS_* constants, while the "stageId" Attribute corresponds to
    the stage in the workflow (WORKFLOW_STAGE_ID_*)
    :param article: an instance of submission.Article
    :param article_dict: The OJS3 submission deserialised into a dict
    """
    stage = None

    if article_dict["status"] in {STATUS_PUBLISHED, STATUS_SCHEDULED}:
        stage = sm_models.STAGE_PUBLISHED
        create_workflow_log(
            article, sm_models.STAGE_READY_FOR_PUBLICATION
        )

    for id, stage_dict in WORKFLOW_STAGE_MAP.items():
        # Create all workflow logs for previoys stages
        if id <= article_dict["stageId"] and stage_dict["workflow"]:
            create_workflow_log(article, stage_dict["workflow"])
        if id == article_dict["stageId"] and not stage:
            stage = stage_dict["stage"]

    if not stage:
        stage = sm_models.STAGE_UNASSIGNED

    article.stage = stage
    article.save()
