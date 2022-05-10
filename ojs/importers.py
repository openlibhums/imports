import os
import re
from datetime import timedelta
from urllib import parse as urlparse
import uuid

from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone, translation
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe
from django.template.defaultfilters import linebreaksbr

from core import models as core_models, files as core_files
from copyediting import models as copyediting_models
from identifiers import models as identifiers_models
from journal import models as journal_models
from metrics import models as metrics_models
from production import models as production_models
from review import models as review_models
from submission import models as submission_models
from utils import setting_handler
from utils.logger import get_logger

from plugins.imports import utils
try:
    from plugins.typesetting import plugin_settings as typesetting_settings
except ImportError:
    typesetting_settings = None

logger = get_logger(__name__)
# Set date time to 12 UTC to ensure correct date for timezone
HOUR = 12

# Parse emails from "display name <some@email.com>"
DISPLAY_NAME_EMAIL_RE = re.compile("<([^>]+)>")

"""
REVIEW RECOMMENDATIONS FROM OJS
define('SUBMISSION_REVIEWER_RECOMMENDATION_ACCEPT', 1);
define('SUBMISSION_REVIEWER_RECOMMENDATION_PENDING_REVISIONS', 2);
define('SUBMISSION_REVIEWER_RECOMMENDATION_RESUBMIT_HERE', 3);
define('SUBMISSION_REVIEWER_RECOMMENDATION_RESUBMIT_ELSEWHERE', 4);
define('SUBMISSION_REVIEWER_RECOMMENDATION_DECLINE', 5);
define('SUBMISSION_REVIEWER_RECOMMENDATION_SEE_COMMENTS', 6);

EDITOR DECISIONS FROM OJS
define('SUBMISSION_EDITOR_DECISION_ACCEPT', 1);
define('SUBMISSION_EDITOR_DECISION_PENDING_REVISIONS', 2);
define('SUBMISSION_EDITOR_DECISION_RESUBMIT', 3);
define('SUBMISSION_EDITOR_DECISION_DECLINE', 4);
"""

REVIEW_RECOMMENDATION = {
    '2': 'minor_revisions',
    '6': 'minor_revisions',
    '3': 'major_revisions',
    '4': 'reject',
    '5': 'reject',
    '1': 'accept',
}


DRAFT_DECISION_STATUS = {
    'accepted': 'accept',
    'declined': 'decline',
    'draft': None,
}


ROLES = {
    "user.role.editor":         "editor",
    "user.role.manager":        "editor",
    "user.role.reviewer":       "reviewer",
    "user.role.layoutEditor":   "typesetter",
    "user.role.copyeditor":     "copyeditor",
    "user.role.sectionEditor":  "section-editor",
    "user.role.proofreader":    "proofreader",
}

ROLES_PRETTY = {
    "Section Editor":   "section-editor",
    "Editor":           "editor",
}


GALLEY_TYPES = {
    "PDF":  "pdf",
    "XML":  "xml",
    "HTML": "html",
}


def import_article_metadata(article_dict, journal, client):
    """ Creates or updates an article record given the OJS metadata"""
    logger.info("Processing OJS ID %s" % article_dict["ojs_id"])
    article, created = get_or_create_article(article_dict, journal)
    if created:
        logger.info("Created article %d" % article.pk)
    else:
        logger.info("Updating article %d" % article.pk)

    # Check for editors and assign them as section editors.
    editors = article_dict.get('editors', [])

    for editor_ass in editors:
        try:
            ed_email = clean_email(editor_ass["email"])
            acc = core_models.Account.objects.get(email__iexact=ed_email)
            if editor_ass["role"] == 'editor':
                acc.add_account_role('editor', journal)
            elif editor_ass["role"] == 'section-editor':
                acc.add_account_role('section-editor', journal)
            review_models.EditorAssignment.objects.update_or_create(
                article=article, editor=acc,
                defaults={"editor_type": editor_ass["role"]},
            )
            logger.info(
                'Editor %s added to article %s' % (acc.email, article.pk))
        except Exception as e:
            logger.error('Editor account was not found.')
            logger.exception(e)

    # Add keywords
    keywords = article_dict.get('keywords')
    if keywords:
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
    emails = set()
    for author in sorted(article_dict.get('authors'),
                         key=lambda x: x.get("sequence", 1)):
        author_record, _ = get_or_create_account(author)
        author_record.add_account_role("author", journal)

        # Add authors to m2m and create an order record
        article.authors.add(author_record)
        order, _ = submission_models.ArticleAuthorOrder.objects.get_or_create(
            article=article,
            author=author_record,
        )
        order.order = author.get("sequence", 999)
        create_frozen_record(author_record, article, emails, author_dict=author)

    # Set the primary author
    email = clean_email(article_dict.get('correspondence_author'))
    article.owner = core_models.Account.objects.get(
        email__iexact=email)
    article.correspondence_author = article.owner
    article.save()

    # Get or create the article's section
    section_name = article_dict.get('section', 'Article')
    section, _ = submission_models.Section.objects.get_or_create(journal=journal, name=section_name)

    article.section = section

    # Set the license if it hasn't been set yet
    if not article.license:
        license_url = article_dict.get("license", "")
        if license_url:
            license_url = license_url.replace("http:", "https:")
            article.license, _ = submission_models.Licence.objects.get_or_create(
                journal=article.journal,
                url=license_url,
                defaults={
                    "name": "Imported License",
                    "short_name": "imported",
                }
            )
    article.save()

    return article, created


def create_frozen_record(author, article, emails=None, author_dict=None):
    """ Creates a frozen record for the article from author metadata

    We create a frozen record that is not linked to a user
    account. This is because email addresses are not unique for author
    records on OJS, so there will be only a single account for all those
    authors which would then update itself instead of creating a new record
    :param author: an instance of core.models.Account
    :param article: an instance of submission.models.Article
    :param emails: a set cotaining the author emails seen in this article
    """
    try:
        order = submission_models.ArticleAuthorOrder.objects.get(
            article=article, author=author).order
    except submission_models.ArticleAuthorOrder.DoesNotExist:
        order = 1

    frozen_dict = {
        'article': article,
        'first_name': author.first_name,
        'middle_name': author.middle_name,
        'last_name': author.last_name,
        'institution': author.institution or '',
        'order': order,
               'author': author,
    }
    if author_dict:
        frozen_dict["first_name"] = author_dict["first_name"]
        frozen_dict["last_name"] = author_dict["last_name"]
        frozen_dict["middle_name"] = author_dict["middle_name"]
        frozen_dict["institution"] = author_dict["affiliation"] or " "
    submission_models.FrozenAuthor.objects.get_or_create(**frozen_dict)


def import_review_data(article_dict, article, client):
    ojs_id = article_dict["ojs_id"]
    # Add first review round
    if article_dict.get("current_review_round"):
        for n in range(1, article_dict["current_review_round"] + 1):
            round, _ = review_models.ReviewRound.objects.get_or_create(
                article=article, round_number=n,
            )
    else:
        round, _ = review_models.ReviewRound.objects.get_or_create(
            article=article, round_number=1,
        )

    # Get MS File
    manuscript_json = article_dict["manuscript_file"]
    manuscript = import_file(client, manuscript_json, article, "manuscript")
    if manuscript:
        article.manuscript_files.add(manuscript)

    # Check for a file for review
    file_for_review_json = article_dict["review_file"]
    file_for_review = import_file(
        client, file_for_review_json, article, "File for Peer-Review")
    if file_for_review:
        round.review_files.add(file_for_review)
    elif article_dict.get("reviews") and manuscript:
        # There are review assignments but no file for review, use manuscript
        round.review_files.add(manuscript)

    # Check for an editor version
    editor_version_json = article_dict["editor_file"]
    editor_version = import_file(
        client, editor_version_json, article, "Editor Review Version")
    if editor_version:
        article.manuscript_files.add(editor_version)

    author_revision_json = article_dict["author_revision"]
    author_revision = import_file(
        client, author_revision_json, article, "Author Revision")
    if author_revision:
        article.manuscript_files.add(author_revision)

    # Attempt to get the default review form
    try:
        form = review_models.ReviewForm.objects.get(
            journal=article.journal,
            slug="default-form",
        )
    except review_models.ReviewForm.DoesNotExit:
        logger.error(
            'You must have at least one review form for the journal before'
            ' importing.'
        )
        raise

    # Set for avoiding duplicate review files
    for review in article_dict.get('reviews'):
        decision = article_dict.get("latest_editor_decision")
        import_review_assignment(client, article, review, form, decision)

    # Get Supp Files
    if article_dict.get('supp_files'):
        for supp_json in article_dict.get('supp_files'):
            supp = import_file(
                client, supp_json, article, "Supplementary File")
            if supp:
                article.data_figure_files.add(supp)
                round.review_files.add(supp)
    if article_dict.get("draft_decisions"):
        handle_draft_decisions(article, article_dict["draft_decisions"])

    if article_dict.get("latest_editor_decision"):
        import_editorial_decision(client, article_dict, article, author_revision)

    article.save()
    round.save()

    return article


def import_review_assignment(client, article, review, review_form, decision):
    reviewer, _ = get_or_create_account(review)
    reviewer.add_account_role("author", article.journal)


    # Parse the dates
    date_requested = timezone.make_aware(
        dateparser.parse(review.get('date_requested')).replace(hour=HOUR)
    )
    date_due = timezone.make_aware(
        dateparser.parse(review.get('date_due')).replace(hour=HOUR))
    date_complete = timezone.make_aware(
        dateparser.parse(review.get('date_complete')).replace(hour=HOUR)) if review.get(
        'date_complete') else None
    date_confirmed = timezone.make_aware(
        dateparser.parse(review.get('date_confirmed')).replace(hour=HOUR)) if review.get(
        'date_confirmed') else None
    date_declined = None
    date_accepted = date_confirmed

    review_defaults = dict(
        review_type='traditional',
        visibility='double-blind',
        date_due=date_due,
        date_requested=date_requested,
        date_complete=date_complete,
        date_accepted=date_accepted,
        date_declined=date_declined,
        access_code=uuid.uuid4(),
        form=review_form
    )

    new_review, _ = review_models.ReviewAssignment.objects.get_or_create(
        article=article,
        reviewer=reviewer,
        review_round=review_models.ReviewRound.objects.get(
            article=article, round_number=review["round"]),
        defaults=review_defaults,
    )

    if review.get('recommendation'):
        new_review.decision = REVIEW_RECOMMENDATION[
            review['recommendation']]
        new_review.is_complete = True

    if decision:
        new_review.for_author_consumption = True
        new_review.display_review_file = True

    if review.get("cancelled"):
        new_review.decision = "withdrawn"

    if review.get('declined'):
        new_review.date_accepted = None
        new_review.date_declined = date_confirmed
        new_review.date_complete = None
        new_review.is_complete = True

    # Check for files at article level
    review_file_json = review.get("review_file")
    review_file_url = review.get("review_file_url")
    if review_file_json:
        review_file = import_file(
            client, review_file_json, article, "Review File",
            owner=reviewer,
        )
        new_review.review_file = review_file
    elif review_file_url:
        fetched_review_file = client.fetch_file(review_file_url)
        if fetched_review_file:
            review_file = core_files.save_file_to_article(
                fetched_review_file, article, reviewer,
                label="Review File",
            )
            new_review.review_file = review_file
    if review.get('comments'):
        handle_review_comment(
            article, new_review, review['comments'],
            review_form, public=True)
    if review.get('comments_to_editor'):
        new_review.comments_for_editor = review["comments_to_editor"]

    new_review.save()


def import_editorial_decision(client, article_dict, article, revision=None):
    decision_code = article_dict["latest_editor_decision"]["decision"]

    # Article has been accepted
    if decision_code == "1":
        article.date_accepted = timezone.make_aware(dateparser.parse(
            article_dict["latest_editor_decision"]["dateDecided"]
        ))

    # Revisions have been requested
    elif decision_code in {"2", "3"}:
        try:
            ed = core_models.Account.objects.get(email__iexact=article_dict[
                "latest_editor_decision"
            ]["editor"]),
        except core_models.Account.DoesNotExist:
            # An old assignment from an account that no longer exists
            logger.warning(
                "Ignoring revision assignment from unknown account: %s",
                article_dict["latest_editor_decision"]["editor"],
            )
            return
        date_decided = timezone.make_aware(dateparser.parse(
            article_dict["latest_editor_decision"]["dateDecided"]
        ))
        request, c = review_models.RevisionRequest.objects.update_or_create(
            article=article,
            defaults={
                "editor_note": "Revision notes have been sent by email",
                "type": REVIEW_RECOMMENDATION[decision_code],
                "date_requested": date_decided,
                "date_due": date_decided + timedelta(days=14),
                "editor": core_models.Account.objects.get(
                    email__iexact=article_dict[
                        "latest_editor_decision"
                    ]["editor"]),
            }
        )

        # Handle author having uploaded a revised MS
        if revision and revision.date_uploaded >= date_decided:
            request.date_completed = revision.date_uploaded
            request.save()
            request.actions.update_or_create(
                text="Author Uplaoded: %s" % revision.original_filename,
                defaults={
                    "logged": revision.date_uploaded,
                    "user": article.owner,
                }
            )


def handle_draft_decisions(article, draft_decisions):
    for key, draft in draft_decisions.items():
        section_editor = core_models.Account.objects.get(
            email__iexact=draft["section_editor"])

        # Append unique key to note for idempotency
        note = key + "\n" + (draft["note"] or "")
        if draft["recommendation"] == "0":
            # MS: I found a couple of currpted instances like this
            continue
        review_models.DecisionDraft.objects.update_or_create(
            article=article,
            message_to_editor=note,
            defaults={
                "email_message": draft["body"] or None,
                "decision": REVIEW_RECOMMENDATION[draft["recommendation"]],
                "section_editor": section_editor,
                "editor_decision": DRAFT_DECISION_STATUS[draft["status"]]
            }
        )


def handle_review_comment(article, review_obj, comment, form, public=True):
    element = form.elements.filter(kind="textarea", name="Review").first()
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

    return review_obj


def import_copyediting(article_dict, article, client):
    """ Imports copyediting files and 'signoffs' into Janeway.

    OJS is very flexible during copyediting. There are 3 main copyediting
    stages:
        - Initial Copyedit
        - Author Copyedit
        - Final Copyedit
    For each stage there will be 3 signoff timestamps:
        - Notified
        - Underway
        - Complete

    It is possible for editors to ignore the signoffs and upload each of the
    3 files above directly, so the API will return the signoffs and the files
    separately.
    """
    copyediting = article_dict.get('copyediting', None)
    imported_files = set()

    if copyediting:
        # Signoffs
        initial = copyediting.get('initial')
        author = copyediting.get('author')
        final = copyediting.get('final')

        if initial:
            email = clean_email(initial.get('email'))
            copyedit_file_json = initial.get("file")
            initial_copyeditor = core_models.Account.objects.get(
                email__iexact=email)
            initial_decision = 'accept' if (
                initial.get('underway')
                or initial.get('complete')
                or initial.get('file')
            ) else None

            assigned = attempt_to_make_timezone_aware(initial.get('notified'))
            underway = attempt_to_make_timezone_aware(initial.get('underway'))
            complete = attempt_to_make_timezone_aware(initial.get('complete'))
            upload_date = complete
            if initial["file"] and not upload_date:
                # OJS might not close the task after file uploaded
                upload_date = initial["file"]["date_uploaded"] or timezone.now()

            copyedit_assignment = copyediting_models\
                .CopyeditAssignment.objects.create(
                    article=article,
                    copyeditor=initial_copyeditor,
                    assigned=assigned or timezone.now(),
                    notified=True,
                    decision=initial_decision,
                    date_decided=underway if underway else complete,
                    copyeditor_completed=upload_date,
                    copyedit_accepted=complete,
                )

            if copyedit_file_json:
                decision = ''
                initial_version = import_file(
                    client, copyedit_file_json, article, "Initial copyedit")
                copyedit_assignment.copyeditor_files.add(initial_version)
                imported_files.add("initial_file")

            if author.get('notified'):
                logger.info('Adding author review.')
                assigned = attempt_to_make_timezone_aware(
                    author.get('notified'))
                complete = attempt_to_make_timezone_aware(
                    author.get('complete'))
                author_file_json = author.get("file")
                if author_file_json and not complete:
                    complete = assigned or timezone.now()

                author_review = copyediting_models.AuthorReview.objects.create(
                    author=article.owner,
                    assignment=copyedit_assignment,
                    assigned=assigned or timezone.now(),
                    notified=True,
                    decision='accept' if complete else None,
                    date_decided=complete,
                )

                if author_file_json:
                    author_version = import_file(
                        client, author_file_json, article, "Author copyedit")
                    author_review.files_updated.add(author_version)
                    imported_files.add("author_file")

            if final and final.get('notified'):
                logger.info('Adding final copyedit assignment.')

                assigned = attempt_to_make_timezone_aware(
                    initial.get('notified'))
                underway = attempt_to_make_timezone_aware(
                    initial.get('underway'))
                complete = attempt_to_make_timezone_aware(
                    initial.get('complete'))

                final_decision = True if underway or complete else False
                final_file_json = final.get("file")
                if final_file_json and not complete:
                    complete = assigned or timezone.now()

                final_assignment = copyediting_models.\
                    CopyeditAssignment.objects.create(
                        article=article,
                        copyeditor=initial_copyeditor,
                        assigned=assigned,
                        notified=True,
                        decision=final_decision,
                        date_decided=underway if underway else complete,
                        copyeditor_completed=complete,
                        copyedit_accepted=complete,
                    )
                if final_file_json:
                    final_version = import_file(
                        client, final_file_json, article, "Final copyedit")
                    final_assignment.copyeditor_files.add(final_version)
                    imported_files.add("final_file")

        # Handle files uploaded outside the OJS signoff workflow
        if "initial_file" not in imported_files and copyediting["initial_file"]:
            import_file(
                client, copyediting["initial_file"],
                article, "Initial copyedit"
            )
        if "author_file" not in imported_files and copyediting["author_file"]:
            import_file(
                client, copyediting["author_file"], article, "Author copyedit")
        if "final_file" not in imported_files and copyediting["final_file"]:
            import_file(
                client, copyediting["final_file"], article, "Final copyedit")


def import_typesetting(article_dict, article, client, with_galleys=None):
    if article.journal.element_in_workflow("Typesetting Plugin"):
        return import_typesetting_plugin(article_dict, article, client)
    layout = article_dict.get('layout')
    task = None

    typesetter = None
    if layout.get('email'):
        if layout.get('email'):
            email = clean_email(layout.get('email'))
            typesetter = core_models.Account.objects.get(
                email__iexact=email)
    elif layout["sent_for_typesetting"]:
        try:
            typesetter = core_models.AccountRole.objects.filter(
                role__slug="typesetter",
                journal=article.journal,
                ).first().user
        except AttributeError:
            logger.warning(
                "Journal %s has no typesetters setup", article.journal.code)

    if typesetter:
        logger.info(
            'Adding typesetter {name}'.format(name=typesetter.full_name()))

        assignment_defaults = dict(
            assigned=timezone.now(),
            notified=True
        )
        assignment, _ = production_models.\
            ProductionAssignment.objects.get_or_create(
                article=article,
                defaults=assignment_defaults,
            )

        assigned = attempt_to_make_timezone_aware(layout.get('notified'))
        accepted = attempt_to_make_timezone_aware(layout.get('underway'))
        complete = attempt_to_make_timezone_aware(layout.get('complete'))
        if not assigned:
            assigned = article.date_submitted

        task, _ = production_models.TypesetTask.objects.get_or_create(
            assignment=assignment,
            typesetter=typesetter,
            assigned=assigned,
            accepted=accepted,
            completed=complete,
        )

    galleys = None
    if with_galleys:
        galleys = import_galleys(article, layout, client)

    if task and galleys:
        for galley in galleys:
            task.galleys_loaded.add(galley.file)


def import_typesetting_plugin(article_dict, article, client, with_galleys=True):
    from plugins.typesetting import models as typesetting_models
    layout = article_dict.get('layout')
    task = None
    typesetter = None
    if layout.get('email'):
        email = clean_email(layout.get('email'))
        typesetter = core_models.Account.objects.get(
            email__iexact=email)
    elif layout["sent_for_typesetting"]:
        try:
            typesetter = core_models.AccountRole.objects.filter(
                role__slug="typesetter",
                journal=article.journal,
                ).first().user
        except core_models.AccountRole.DoesNotExist:
            logger.warning(
                "Journal %s has no typesetters setup", article.journal.code)

    if typesetter and not layout.get("galleys"):
        sent = attempt_to_make_timezone_aware(layout.get('sent_for_typesetting'))
        assigned = attempt_to_make_timezone_aware(layout.get('notified')) or sent
        accepted = attempt_to_make_timezone_aware(layout.get('underway')) or sent
        complete = attempt_to_make_timezone_aware(layout.get('complete'))

        logger.info(
            'Adding typesetter {name}'.format(name=typesetter.full_name()))

        round, _ = typesetting_models.TypesettingRound.objects.get_or_create(
            article=article,
            defaults={"date_created": assigned}
        )


        task, _ = typesetting_models.TypesettingAssignment.objects.get_or_create(
            round=round,
            typesetter=typesetter,
            defaults={
                "assigned": assigned,
                "notified": bool(assigned),
                "accepted": accepted,
                "completed": complete,
            }
        )
    if with_galleys:
        galleys = import_galleys(article, layout, client, owner=typesetter)


def import_publication(article_dict, article, client):
    """ Imports an article-issue relationship
    If the issue doesn't exist yet, it gets created
    """
    pub_data = article_dict.get("publication", {})
    if pub_data.get('date_published'):
        article.date_published = timezone.make_aware(
            dateparser.parse(pub_data.get('date_published')).replace(hour=HOUR)
        )
        article.save()
    if pub_data and pub_data.get("number"):
        issue = get_or_create_issue(pub_data, article.journal)

        article.primary_issue = issue
        article.save()
        issue.articles.add(article)

        if issue.date and not article.date_published:
            article.date_published = issue.date
            article.save()


def import_issue_metadata(issue_dict, client, journal):
    issue = get_or_create_issue(issue_dict, journal)
    issue.order = int(issue_dict.get("sequence", 0))

    # Handle cover
    if issue_dict.get("cover") and not issue.cover_image:
        issue_cover = client.fetch_file(issue_dict["cover"])
        issue.cover_image = issue_cover
    issue.save()

    # Handle Section orderings
    for section_order, section_dict in enumerate(
        issue_dict.get("sections", []), 1
    ):
        section_name = section_dict["title"]
        section, _ = submission_models.Section.objects.get_or_create(journal=journal, name=section_name)
        journal_models.SectionOrdering.objects.get_or_create(
            issue=issue,
            section=section,
            defaults={"order": section_order}
        )

        for order, article_dict in enumerate(section_dict.get("articles", [])):
            import_article_section(article_dict, issue, section, order)

    return issue


def import_collection_metadata(collection_dict, client, journal):
    collection = get_or_create_collection(collection_dict, journal)

    # Handle cover
    if collection_dict.get("cover_file"):
        collection_img = client.fetch_file(collection_dict["cover_file"])
        file_name = os.path.basename(collection_dict["cover_file"]) or "cover.graphic"
        if collection_img:
            collection.cover_image.save(file_name, collection_img)
        else:
            logger.warning(
                "Couldn't retrieve collection image: %s",
                collection_dict["cover_file"],
            )
    collection.save()

    # Handle Section orderings
    for i, ojs_id in enumerate(
        collection_dict.get("article_ids", []), 1
    ):
        link_article_to_collection(collection, ojs_id, order=i)

    return collection


def import_journal_settings(settings_dict, journal):
    if 'focusScopeDesc' in settings_dict:
        import_multilingual_setting("general", "focus_and_scope", journal, settings_dict.get("focusScopeDesc"))



def import_multilingual_setting(group, setting_name, journal, setting_dict):
    """ Import a multilingual setting from OJS into the Janeway journal
    """
    default_lang = settings.LANGUAGE_CODE
    values = []
    for locale, value in setting_dict.items():
        lang_code = locale_to_lang(locale)
        if lang_code and value:
            with translation.activate(lang_code):
                print(setting_name, lang_code, value)
                #save_setting( group, setting_name, journal, value)


def import_section_metadata(section_dict, client, journal):
    section, _ = submission_models.Section.objects.get_or_create(
        journal=journal,
        name=section_dict["title"],
    )
    section.public_submissions = section_dict["open_submissions"]
    section.indexing = section_dict["indexed"]
    section.sequence = section_dict["sequence"]

    auto_assign_editors = None
    for editor_dict in section_dict["editors"]:
        account = core_models.Account.objects.get(
            email__iexact=editor_dict["email"])
        if editor_dict["review"] or editor_dict["edit"]:
            auto_assign_editors = True
            section.section_editors.add(account)

    if not section_dict["peer_reviewed"]:
        section.number_of_reviewers = 0
    if auto_assign_editors is not None:
        section.auto_assign_editors = auto_assign_editors

    section.save()
    return section


def import_article_section(article_section_dict, issue, section, order):
    ojs_id = article_section_dict["id"]
    try:
        article = identifiers_models.Identifier.objects.get(
            id_type="ojs_id",
            identifier=ojs_id,
            article__journal=section.journal,
        ).article
    except identifiers_models.Identifier.DoesNotExist:
        logger.warning(
            "Article section record for unimported article with OJS id "
            "%s" % ojs_id,
        )
    else:
        article.section = section
        article.page_numbers = article_section_dict.get("pages")
        article.save()

        ordering, _ = journal_models.ArticleOrdering.objects.get_or_create(
            issue=issue,
            article=article,
            section=section,
        )
        ordering.order = order
        ordering.save()

def link_article_to_collection(collection, ojs_id, order):
    try:
        article = identifiers_models.Identifier.objects.get(
            id_type="ojs_id",
            identifier=ojs_id,
            article__journal=collection.journal,
        ).article
    except identifiers_models.Identifier.DoesNotExist:
        logger.warning(
            "Collection %s has non-existant OJS ID %d", collection, ojs_id
        )
    collection.articles.add(article)
    if not article.primary_issue:
        article.primary_issue = collection
        article.save()
    ordering, _ = journal_models.ArticleOrdering.objects.update_or_create(
        issue=collection,
        article=article,
        section=article.section,
        defaults={"order": order},
    )


def import_galleys(article, layout_dict, client, owner=None):
    galleys = list()
    if not owner:
        owner = article.owner

    if layout_dict.get('galleys'):
        for galley in layout_dict.get('galleys'):
            logger.info(
                'Adding Galley with label {label}'.format(
                    label=galley.get('label')
                )
            )
            if not galley.get("file") or galley["file"] == "None":
                logger.warning("Can't fetch galley: %s", galley)
                continue
            galley_file = import_file(
                client, galley.get("file"), article, galley.get("label"),
                owner=owner,
            )
            if galley_file:
                new_galley, c = core_models.Galley.objects.update_or_create(
                    article=article,
                    type=GALLEY_TYPES.get(galley.get("label"), "other"),
                    defaults={
                        "label": galley.get("label"),
                        "file": galley_file,
                    },
                )
                if c:
                    galleys.append(new_galley)

    return galleys


def calculate_article_stage(article_dict, article):
    """ Works out the article stage assuming a standard workflow

    Traverses workflow upwards, creating WorkflowLog objects where
    necessary.
    """
    typesetting_plugin = article.journal.element_in_workflow(
        "Typesetting Plugin")
    stage = submission_models.STAGE_UNASSIGNED
    if article_dict.get("review_file_url") or article_dict.get("reviews"):
        stage = submission_models.STAGE_UNDER_REVIEW
        try:
            create_workflow_log(article, stage)
        except ObjectDoesNotExist:
            # On 1.3.9 STAGE_UNASSIGNED is actually the first stage of review
            create_workflow_log(article, submission_models.STAGE_UNASSIGNED)

    if any(article_dict["copyediting"].values()):
        stage = submission_models.STAGE_EDITOR_COPYEDITING
        create_workflow_log(article, stage)

    if (
        article_dict["layout"]["galleys"]
        or article_dict["layout"]["layout_file"]
    ):
        if typesetting_plugin:
            stage = typesetting_settings.STAGE
            create_workflow_log(article, stage)
        else:
            stage = submission_models.STAGE_TYPESETTING
            create_workflow_log(article, stage)

    if article_dict.get("proofing"):
        if not typesetting_plugin:
            # Typesetting plugin handles proofing
            stage = submission_models.STAGE_PROOFING
            create_workflow_log(article, stage)

    if article_dict.get('publication') and article.date_published:
        stage = submission_models.STAGE_PUBLISHED
        create_workflow_log(article, submission_models.STAGE_READY_FOR_PUBLICATION)

    return stage


def create_workflow_log(article, stage):
    element = core_models.WorkflowElement.objects.get(
        journal=article.journal,
        stage=stage,
    )

    return core_models.WorkflowLog.objects.get_or_create(
        article=article,
        element=element,
    )


def get_or_create_article(article_dict, journal):
    """Get or create article, looking up by OJS ID or DOI"""
    created = False
    date_started = timezone.make_aware(
        dateparser.parse(article_dict.get('date_submitted')).replace(hour=HOUR))

    doi = article_dict.get("doi")
    ojs_id = article_dict["ojs_id"]

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
            title=article_dict.get('title'),
            abstract=article_dict.get('abstract'),
            language=article_dict.get('language'),
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


def import_article_metrics(ojs_id, journal, views=0, downloads=0):
    try:
        article = identifiers_models.Identifier.objects.get(
            id_type="ojs_id",
            identifier=ojs_id,
            article__journal=journal,
        ).article
    except identifiers_models.Identifier.DoesNotExist:
        logger.warning(
            "Article metric record for unimported article with OJS id "
            "%s" % ojs_id,
        )
        return

    metric, _ = metrics_models.HistoricArticleAccess.objects.get_or_create(
        article=article,
        defaults={"downloads": 0, "views": 0}
    )
    if views:
        metric.views = views
    if downloads:
        metric.downloads = downloads
    metric.save()


def import_user_metadata(user_data, journal):
    created = False
    if len(user_data["roles"]) == 0:
        return None, created
    elif len(user_data["roles"]) == 1 and user_data["roles"][0] == "user.role.reader":
        return None, created
    account, created = get_or_create_account(user_data)
    for ojs_role in user_data.get("roles"):
        janeway_role = ROLES.get(ojs_role)
        if janeway_role:
            account.add_account_role(janeway_role, journal)

    account.add_account_role("author", journal)
    account.is_active = True
    account.save()
    return account, created


def get_or_create_account(data, update=False):
    """ Gets or creates an account for the given OJS user data"""
    email = clean_email(data.get("email"))
    created = False
    try:
        account = core_models.Account.objects.get(
            email=email)
    except core_models.Account.DoesNotExist:
        try:
            account = core_models.Account.objects.create(
                email=email,
            )
            created = True
        except Exception as e:
            #Most likely due to a problem with case
            try:
                account = core_models.Account.objects.get(
                    email__iexact=email)
            except Exception as e:
                logger.warning("Failed to create user %s" % data)
                return None, created

    if created or update:
        account.salutation = data.get("salutation")
        if account.salutation and len(account.salutation) > 9:
            # OJS does not sanitise this field.
            account.salutation = None
        account.first_name = data.get('first_name')
        account.middle_name = data.get('middle_name')
        account.last_name = data.get('last_name')
        account.institution = data.get('affiliation', ' ') or ' '
        account.biography = data.get('bio')
        account.orcid = extract_orcid(data.get("orcid"))


        if data.get('country'):
            try:
                country = core_models.Country.objects.get(
                    code=data.get('country'))
                account.country = country
                account.save()
            except core_models.Country.DoesNotExist:
                pass

        account.save()
    return account, created


def get_or_create_issue(issue_data, journal):
    issue_num = int(issue_data.get("number", 1))
    vol_num = int(issue_data.get("volume", 1))
    year = issue_data.get("year")
    date_published = attempt_to_make_timezone_aware(
        issue_data.get("date_published"),
    )

    issue, created = journal_models.Issue.objects.get_or_create(
        journal=journal,
        volume=vol_num,
        issue=issue_num,
        issue_type__code="issue",
        defaults={
            "date": date_published or timezone.now(),
            "issue_title": issue_data.get("title"),
        },
    )
    if created:
        issue_type = journal_models.IssueType.objects.get(
            code="issue", journal=journal)
        issue.issue_type = issue_type
        if issue_data.get("description"):
            issue.issue_description = issue_data["description"]
        issue.save()
        logger.info("Created new issue {}".format(issue))

    # Handle missmatch betwen issue date_published and issue year
    if year and (
        not date_published
        or issue.date.year != int(year)
    ):
        issue.date = issue.date.replace(year=int(year))
        issue.save()

    return issue


def get_or_create_collection(collection_data, journal):
    collection_id = int(collection_data.get("id", 1))
    date_published = attempt_to_make_timezone_aware(
        collection_data.get("date_published"),
    )
    issue_type = journal_models.IssueType.objects.get(
        code="collection", journal=journal)

    collection, created = journal_models.Issue.objects.update_or_create(
        journal=journal,
        volume=collection_id,
        issue_type=issue_type,
        defaults={
            "date": date_published or timezone.now(),
            "issue_title": collection_data.get("title"),
            "short_description": collection_data.get("short_description"),
            "issue_description": collection_data.get("description"),
        },
    )
    if created:
        logger.info("Created new issue {}".format(collection))

    return collection


def scrape_editor_assignments(client, ojs_id, article):
    """ Imports editor assignments by scraping them

    Not required since ojs-janeway v1.1
    Expected html structure
    <form action="{url}/setEditorFlags">
        <table>
        <tr valign="top">
            <td>(Section )Editor</td>
            <td><a href="{emailink}">{editor_name}</td>
    [...]
    """
    url = client.journal_url + client.SUBMISSION_PATH % ojs_id
    resp = client.fetch(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")
    form = soup.find(
        "form", {"action": re.compile("setEditorFlags$")})
    rows = form.find_all("tr", {"valign": "top"})
    for row in rows:
        # Parse assigned role
        role_c, mailto_c, *_, date_c, _ = row.find_all("td")
        role_name = ROLES_PRETTY.get(role_c.text)

        # get editor account
        mailto_url = mailto_c.find("a")["href"]
        display_name = get_query_param(mailto_url, "to[]")[0]
        editor_email = DISPLAY_NAME_EMAIL_RE.findall(display_name)[0]
        editor, _ = get_or_create_account({"email": editor_email}, update=False)
        editor.add_account_role("author", article.journal)

        # Get assignment date
        try:
            date_assigned = timezone.make_aware(
                dateparser.parse(date_c.text)
            )
        except ValueError:
            date_assigned = article.date_submitted
        review_models.EditorAssignment.objects.update_or_create(
            article=article,
            editor=editor,
            defaults={
                "editor_type": role_name,
                "assigned": date_assigned,
            }
        )


def attempt_to_make_timezone_aware(datetime):
    if datetime:
        dt = dateparser.parse(datetime)
        return timezone.make_aware(dt.replace(hour=HOUR))
    else:
        return None


def extract_orcid(raw_orcid_data):
    """ Extracts the orcid from the given raw data from the API
    :param raw_oricid_data: A dict from lang code to orcid URL or actual orcid
    """
    if raw_orcid_data:
        if isinstance(raw_orcid_data, str): return raw_orcid_data
        for lang, value in raw_orcid_data.items():
            if value:
                # ORCID might be in URL format
                try:
                    return utils.orcid_from_url(value)
                except ValueError:
                    return value
    return None


def clean_email(email):
    import unicodedata
    clean = unicodedata.normalize("NFKC", email).strip()
    return clean.split(" ")[0]


def get_query_param(url, param):
    query = urlparse.parse_qs( urlparse.urlsplit(url).query)
    query_dict = dict(query)
    return query_dict.get(param)


def import_file(client, file_json, article, label, file_name=None, owner=None):
    """ Imports an OJS file from the provided JSON metadata"""
    if not file_json or not file_json["url"]:
        return
    django_file = client.fetch_file(file_json["url"], file_name)
    janeway_file = core_files.save_file_to_article(
        django_file, article, owner or article.owner, label=label)
    janeway_file.date_uploaded = attempt_to_make_timezone_aware(
        file_json["date_uploaded"])
    if file_json["mime_type"]:
        janeway_file.mime_type = file_json["mime_type"]
    if file_json["file_name"]:
        janeway_file.original_filename = file_json["file_name"]
    janeway_file.save()

    # Overcome autho_now_add=True
    date_modified = attempt_to_make_timezone_aware(
        file_json["date_modified"] or file_json["date_uploaded"])
    core_models.File.objects.filter(id=janeway_file.pk).update(
        date_modified=date_modified)

    return janeway_file


def locale_to_lang(locale):
    """Return the correct configured language code for the given locale"""
    try:
        # Convert OJS locale to LCID: es_MX -> es-mx
        lang_code = locale.replace("_", "-").lower()
        if lang_code in settings.LANGUAGES:
            return lang_code
        # Try lang code without suffix 'es-mx' -> 'es'
        lang_code, *_ = lang_code.split("-")
        if lang_code in settings.LANGUAGES:
            return lang_code
    except Exception as err:
        logger.warning("unable to parse locale %s: %s", locale, err)
    return None
