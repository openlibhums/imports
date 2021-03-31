import re
from urllib import parse as urlparse
import uuid

from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
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
                acc.add_account_role('editor', journal)
            review_models.EditorAssignment.objects.create(
                article=article, editor=acc, editor_type=editor_ass["role"])
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
        author_record = get_or_create_account(author)

        # Add authors to m2m and create an order record
        article.authors.add(author_record)
        order, _ = submission_models.ArticleAuthorOrder.objects.get_or_create(
            article=article,
            author=author_record,
        )
        order.order = author.get("sequence", 999)
        create_frozen_record(author_record, article, emails)

    # Set the primary author
    email = clean_email(article_dict.get('correspondence_author'))
    article.owner = core_models.Account.objects.get(
        email__iexact=email)
    article.correspondence_author = article.owner
    article.save()

    # Get or create the article's section
    section_name = article_dict.get('section', 'Article')
    section, _ = submission_models.Section.objects.language(
        settings.LANGUAGE_CODE
    ).get_or_create(journal=journal, name=section_name)

    article.section = section
    article.save()

    # Set the license if it hasn't been set yet
    if not article.license:
        license_url = article_dict.get("license", "").replace("http:", "https:")
        article.license, _ = submission_models.Licence.objects.get_or_create(
            journal=article.journal,
            url=license_url,
            defaults={
                "name":"imported license",
                "short_name":"imported",
            }
        )
        article.save()

    return article


def create_frozen_record(author, article, emails=None):
    """ Creates a frozen record for the article from author metadata

    We create a frozen record that is not linked to a user
    account. This is because email addresses are not unique for author
    records on OJS, so there will be only a single account for all those
    authors which would then update itself instead of creating a new record
    :param author: an instance of core.models.Account
    :param article: an instance of submission.models.Article
    :param emails: a set cotaining the author emails seen in this article
    """
    if emails and author.email in emails:
        # Copy behaviour of snapshot_self, without liking acccount
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
            'department': author.department,
            'order': order,
        }

        submission_models.FrozenAuthor.objects.get_or_create(**frozen_dict)

    elif emails is not None:
        author.snapshot_self(article)
        emails.add(author.email)
    else:
        author.snapshot_self(article)


def import_review_data(article_dict, article, client):
    ojs_id = article_dict["ojs_id"]
    # Add first review round
    round, _ = review_models.ReviewRound.objects.get_or_create(
        article=article, round_number=1,
    )

    # Get MS File
    manuscript_file_url = article_dict.get("manuscript_file_url")
    manuscript = client.fetch_file(
        manuscript_file_url, "manuscript",
        # If a file doesn't exist, it redirects to the article page
        # Should probably be handled on the OJS end really
        exc_mimes=core_files.HTML_MIMETYPES,
    )
    if manuscript:
        ms_file = core_files.save_file_to_article(
            manuscript, article, article.owner, label="Manuscript")
        article.manuscript_files.add(ms_file)

    # Check for a file for review
    file_for_review_url = article_dict.get("review_file_url")
    fetched_file_for_review = client.fetch_file(
        file_for_review_url,
        exc_mimes=core_files.HTML_MIMETYPES,
    )
    if fetched_file_for_review:
        file_for_review = core_files.save_file_to_article(
            fetched_file_for_review, article, article.owner,
            label="File for Peer-Review",
        )
        round.review_files.add(file_for_review)
    elif article_dict.get("reviews") and manuscript:
        # There are review assignments but no file for review, use manuscript
        round.review_files.add(ms_file)

    # Attempt to get the default review form
    form = setting_handler.get_setting(
        'general',
        'default_review_form',
        article.journal,
    ).processed_value
    if form:
        form = review_models.ReviewForm.objects.get(
            id=form,
        )

    else:
        try:
            form = review_models.ReviewForm.objects.filter(
                journal=article.journal)[0]
        except Exception:
            form = None
            logger.error(
                'You must have at least one review form for the journal before'
                ' importing.'
            )
            raise

    # Set for avoiding duplicate review files
    for review in article_dict.get('reviews'):
        reviewer = get_or_create_account(review)

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

        review.get('declined')
        if review.get('declined') == '1':
            date_accepted = None
            date_declined = date_confirmed
        else:
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
            form=form
        )
        new_review, _ = review_models.ReviewAssignment.objects.get_or_create(
            article=article,
            reviewer=reviewer,
            review_round=round,
            defaults=review_defaults,
        )

        if review.get('declined') or review.get('recommendation'):
            new_review.is_complete = True

        if review.get('recommendation'):
            new_review.decision = REVIEW_RECOMMENDATION[
                review['recommendation']]

        # Check for files at article level
        review_file_url = review.get("review_file_url")
        if review_file_url:
            fetched_review_file = client.fetch_file(review_file_url)
            if fetched_review_file:
                review_file = core_files.save_file_to_article(
                    fetched_review_file, article, reviewer,
                    label="Review File",
                )
                new_review.review_file = review_file

        if review.get('comments'):
            handle_review_comment(
                article, new_review, review.get('comments'), form)

        new_review.save()


    # Get Supp Files
    if article_dict.get('supp_files'):
        for supp in article_dict.get('supp_files'):
            supp = client.fetch_file(supp["url"], supp["title"])
            if supp:
                ms_file = core_files.save_file_to_article(
                    supp, article, article.owner, label="Supplementary File")
                article.data_figure_files.add(ms_file)
                round.review_files.add(ms_file)
    if article_dict.get("draft_decisions"):
        handle_draft_decisions(article, article_dict["draft_decisions"])

    article.save()
    round.save()

    return article


def handle_draft_decisions(article, draft_decisions):
    for key, draft in draft_decisions.items():
        editor = core_models.Account.objects.get(email__iexact=draft["editor"])
        section_editor = core_models.Account.objects.get(
                email__iexact=draft["section_editor"])

        # Append unique key to note for idempotency
        note = key + "\n" + draft["note"]
        review_models.DraftDecision.objects.update_or_create(
            article=article,
            message_to_editor=note,
            defaults={
                "email_message": draft["body"] or None,
                "decision": DRAFT_DECISION_STATUS[draft["status"]],
                "section_editor": section_editor,
            }


def handle_review_comment(article, review_obj, comment, form):
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
    copyediting = article_dict.get('copyediting', None)

    if copyediting:
        initial = copyediting.get('initial')
        author = copyediting.get('author')
        final = copyediting.get('final')

        if initial:
            email = clean_email(initial.get('email'))
            copyedit_file_url = initial.get("file")
            initial_copyeditor = core_models.Account.objects.get(
                email__iexact=email)
            initial_decision = 'accept'if (
                initial.get('underway')
                or initial.get('complete')
                or copyedit_file_url
            ) else None

            assigned = attempt_to_make_timezone_aware(initial.get('notified'))
            underway = attempt_to_make_timezone_aware(initial.get('underway'))
            complete = attempt_to_make_timezone_aware(initial.get('complete'))
            file_upload_date = complete
            if copyedit_file_url and not file_upload_date:
                # OJS might not close the task after file uploaded
                file_upload_date = assigned or timezone.now()

            copyedit_assignment = copyediting_models\
                .CopyeditAssignment.objects.create(
                    article=article,
                    copyeditor=initial_copyeditor,
                    assigned=assigned or timezone.now(),
                    notified=True,
                    decision=initial_decision,
                    date_decided=underway if underway else complete,
                    copyeditor_completed=file_upload_date,
                    copyedit_accepted=complete,
                )

            if copyedit_file_url:
                decision = ''
                fetched_copyedit_file = client.fetch_file(copyedit_file_url)
                if fetched_copyedit_file:
                    copyedit_file = core_files.save_file_to_article(
                        fetched_copyedit_file, article, initial_copyeditor,
                        label="Copyedited File")
                    copyedit_assignment.copyeditor_files.add(copyedit_file)

            if initial and author.get('notified'):
                logger.info('Adding author review.')
                assigned = attempt_to_make_timezone_aware(
                    author.get('notified'))
                complete = attempt_to_make_timezone_aware(
                    author.get('complete'))
                author_file_url = author.get("file")
                if author_file_url and not complete:
                    complete = assigned or timezone.now()

                author_review = copyediting_models.AuthorReview.objects.create(
                    author=article.owner,
                    assignment=copyedit_assignment,
                    assigned=assigned or timezone.now(),
                    notified=True,
                    decision='accept',
                    date_decided=complete,
                )

                if author_file_url:
                    fetched_review = client.fetch_file(author_file_url)
                    if fetched_review:
                        author_review_file = core_files.save_file_to_article(
                            fetched_review, article, article.owner,
                            label="Author Review File",
                        )
                        author_review.files_updated.add(author_review_file)

            if final and initial_copyeditor and final.get('notified'):
                logger.info('Adding final copyedit assignment.')

                assigned = attempt_to_make_timezone_aware(
                    initial.get('notified'))
                underway = attempt_to_make_timezone_aware(
                    initial.get('underway'))
                complete = attempt_to_make_timezone_aware(
                    initial.get('complete'))

                final_decision = True if underway or complete else False
                final_file_url = final.get("file")
                if final_file_url and not complete:
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
                if final_file_url:
                    fetched_final = client.fetch_file(final_file_url)
                    if fetched_final:
                        final_file = core_files.save_file_to_article(
                            fetched_final, article, initial_copyeditor,
                            label="Final File",
                        )
                        final_assignment.copyeditor_files.add(final_file)


def import_typesetting(article_dict, article, client):
    if article.journal.element_in_workflow("Typesetting Plugin"):
        return import_typesetting_plugin(article_dict, article, client)
    layout = article_dict.get('layout')
    task = None

    if layout.get('email'):
        email = clean_email(layout.get('email'))
        typesetter = core_models.Account.objects.get(
            email__iexact=email)

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

    galleys = import_galleys(article, layout, client)

    if task and galleys:
        for galley in galleys:
            task.galleys_loaded.add(galley.file)


def import_typesetting_plugin(article_dict, article, client):
    from plugins.typesetting import models as typesetting_models
    layout = article_dict.get('layout')
    task = None
    typesetter = None

    if layout.get('email'):
        email = clean_email(layout.get('email'))
        typesetter = core_models.Account.objects.get(
            email__iexact=email)
        assigned = attempt_to_make_timezone_aware(layout.get('notified'))
        accepted = attempt_to_make_timezone_aware(layout.get('underway'))
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
                "notified": assigned,
                "accepted": accepted,
                "completed": complete,
            }
        )

    galleys = import_galleys(article, layout, client, owner=typesetter)


def import_publication(article_dict, article, client):
    """ Imports an article-issue relationship
    If the issue doesn't exist yet, it gets created
    """
    pub_data = article_dict.get("publication")
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
        section, _ = submission_models.Section.objects.language(
            settings.LANGUAGE_CODE
        ).get_or_create(journal=journal, name=section_name)
        journal_models.SectionOrdering.objects.get_or_create(
            issue=issue,
            section=section,
            defaults={"order": section_order}
        )

        for order, article_dict in enumerate(section_dict.get("articles", [])):
            import_article_section(article_dict, issue, section, order)

    return issue


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
            remote_file = client.fetch_file(
                galley.get("file"), galley.get("label"))
            galley_file = core_files.save_file_to_article(
                remote_file, article, owner, label=galley.get("label"))

            new_galley, c = core_models.Galley.objects.get_or_create(
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

    if article_dict.get("copyediting"):
        stage = submission_models.STAGE_EDITOR_COPYEDITING
        create_workflow_log(article, stage)

    if article_dict.get("layout") and article_dict["layout"].get("galleys"):
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
    account = get_or_create_account(user_data)
    for ojs_role in user_data.get("roles"):
        janeway_role = ROLES.get(ojs_role)
        if janeway_role:
            account.add_account_role(janeway_role, journal)

    account.add_account_role("author", journal)
    account.is_active = True
    account.save()


def get_or_create_account(data, update=True):
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
            account = core_models.Account.objects.get(
            email__iexact=email)

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
    return account


def get_or_create_issue(issue_data, journal):
    issue_num = int(issue_data.get("number", 1))
    vol_num = int(issue_data.get("volume", 1))
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

    return issue


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
        editor = get_or_create_account({"email": editor_email}, update=False)

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
