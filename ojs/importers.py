import uuid

from dateutil import parser as dateparser
from django.conf import settings
from django.utils import timezone

from core import models as core_models, files as core_files
from copyediting import models as copyediting_models
from identifiers import models as identifiers_models
from journal import models as journal_models
from production import models as production_models
from review import models as review_models
from submission import models as submission_models
from utils import setting_handler
from utils.logger import get_logger

logger = get_logger(__name__)


REVIEW_RECOMMENDATION = {
    '2': 'minor_revisions',
    '3': 'major_revisions',
    '5': 'reject',
    '1': 'accept'
}


def import_article_metadata(article_dict, journal, client):
    """ Creates or updates an article record given the OJS metadata"""
    article = get_or_create_article(article_dict, journal)

    # Check for editors and assign them as section editors.
    editors = article_dict.get('editors', [])

    for editor in editors:
        try:
            account = core_models.Account.objects.get(email=editor)
            account.add_account_role('section-editor', journal)
            review_models.EditorAssignment.objects.create(
                article=article, editor=account, editor_type='section-editor')
            logger.info(
                'Editor %s added to article %s' % (editor.email, article.pk))
        except Exception as e:
            logger.error('Editor account was not found.')
            logger.exception(e)

    # Add keywords
    keywords = article_dict.get('keywords')
    if keywords:
        for keyword in keywords.split(';'):
            word, created = submission_models.Keyword.objects.get_or_create(
                word=keyword)
            article.keywords.add(word)

    # Add authors
    for author in article_dict.get('authors'):
        author_record = get_or_create_account(author)

        # Add authors to m2m and create an order record
        article.authors.add(author_record)
        submission_models.ArticleAuthorOrder.objects.create(
            article=article,
            author=author_record,
            order=article.next_author_sort()
        )

        # Set the primary author
        article.owner = core_models.Account.objects.get(
            email=article_dict.get('correspondence_author').lower())
        article.correspondence_author = article.owner

        # Get or create the article's section
        section_name = article_dict.get('section', 'Article')
        section, _ = submission_models.Section.objects.language(
            settings.LANGUAGE_CODE
        ).get_or_create(journal=journal, name=section_name)

        article.section = section

        article.save()

        return article


def import_review_data(article_dict, article, client):
    # Add a new review round
    round, _ = review_models.ReviewRound.objects.get_or_create(
        article=article, round_number=1,
    )

    # Attempt to get the default review form
    form = setting_handler.get_setting(
        'general',
        'default_review_form',
        article.journal,
    ).processed_value

    if not form:
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

    for review in article_dict.get('reviews'):
        reviewer = get_or_create_account(review)

        # Parse the dates
        date_requested = timezone.make_aware(
            dateparser.parse(review.get('date_requested')))
        date_due = timezone.make_aware(
            dateparser.parse(review.get('date_due')))
        date_complete = timezone.make_aware(
            dateparser.parse(review.get('date_complete'))) if review.get(
            'date_complete') else None
        date_confirmed = timezone.make_aware(
            dateparser.parse(review.get('date_confirmed'))) if review.get(
            'date_confirmed') else None

        # If the review was declined, setup a date declined date stamp
        review.get('declined')
        if review.get('declined') == '1':
            date_accepted = None
            date_complete = date_confirmed
        else:
            date_accepted = date_confirmed

        review_defaults = dict(
            review_type='traditional',
            visibility='double-blind',
            date_due=date_due,
            date_requested=date_requested,
            date_complete=date_complete,
            date_accepted=date_accepted,
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

        review_file_url = review.get("review_file_url")
        if review_file_url:
            fetched_review_file = client.fetch_file(review_file_url)
            review_file = core_files.save_file_to_article(
                fetched_review_file, article, reviewer, label="Review File")

            new_review.review_file = review_file
            round.review_files.add(review_file)

        elif review.get('comments'):
            filepath = core_files.create_temp_file(
                review.get('comments'), 'comment.txt')
            f = open(filepath, 'r')
            comment_file = core_files.save_file_to_article(
                f,
                article,
                article.owner,
                label='Review Comments',
                save=False,
            )

            new_review.review_file = comment_file
            round.review_files.add(review_file)

        new_review.save()

    # Get MS File
    manuscript_file_url = article_dict.get("manuscript_file_url")
    manuscript = client.fetch_file(manuscript_file_url, "manuscript")
    ms_file = core_files.save_file_to_article(
        manuscript, article, article.owner, label="Manuscript")
    article.manuscript_files.add(ms_file)

    # Get Supp Files
    if article_dict.get('supp_files'):
        for supp in article_dict.get('supp_files'):
            supp = client.fetch_file(supp["url"], supp["title"])
            ms_file = core_files.save_file_to_article(
                supp, article, article.owner, label="Supplementary File")
            article.data_figure_files.add(supp)

    article.save()
    round.save()

    return article


def import_copyediting(article_dict, article, client):
    copyediting = article_dict.get('copyediting', None)

    if copyediting:
        initial = copyediting.get('initial')
        author = copyediting.get('author')
        final = copyediting.get('final')

        if initial:
            initial_copyeditor = core_models.Account.objects.get(
                email=initial.get('email').lower())
            initial_decision = True if (
                initial.get('underway') or initial.get('complete')) else False

            assigned = attempt_to_make_timezone_aware(initial.get('notified'))
            underway = attempt_to_make_timezone_aware(initial.get('underway'))
            complete = attempt_to_make_timezone_aware(initial.get('complete'))

            copyedit_assignment = copyediting_models\
                .CopyeditAssignment.objects.create(
                    article=article,
                    copyeditor=initial_copyeditor,
                    assigned=assigned,
                    notified=True,
                    decision=initial_decision,
                    date_decided=underway if underway else complete,
                    copyeditor_completed=complete,
                    copyedit_accepted=complete
                )

            copyedit_file_url = initial.get("file")
            if copyedit_file_url:
                fetched_copyedit_file = client.fetch_file(copyedit_file_url)
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

                author_review = copyediting_models.AuthorReview.objects.create(
                    author=article.owner,
                    assignment=copyedit_assignment,
                    assigned=assigned,
                    notified=True,
                    decision='accept',
                    date_decided=complete,
                )

                author_file_url = author.get("file")
                if author_file_url:
                    fetched_review = client.fetch_file(author_file_url)
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
                final_file_url = final.get("file")
                if final_file_url:
                    fetched_final = client.fetch_file(final_file_url)
                    final_file = core_files.save_file_to_article(
                        fetched_final, article, initial_copyeditor,
                        label="Final File",
                    )
                    final_assignment.copyeditor_files.add(final_file)


def import_typesetting(article_dict, article, client):
    layout = article_dict.get('layout')
    task = None

    if layout.get('email'):
        typesetter = core_models.Account.objects.get(
            email__iexact=layout.get('email'))

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


def import_publication(article_dict, article, client):
    pub_data = article_dict.get("publication")
    if pub_data and pub_data.get("issue_number"):
        issue_num = int(pub_data.get("issue_number", 1))
        vol_num = int(pub_data.get("issue_volume", 1))
        date_published = attempt_to_make_timezone_aware(
            pub_data.get("date_published"),
        )

        issue, created = journal_models.Issue.objects.get_or_create(
            journal=article.journal,
            volume=vol_num,
            issue=issue_num,
            issue_title=pub_data.get("issue_title"),
            defaults={"date": date_published},
        )
        if created:
            issue_type = journal_models.IssueType.objects.get(
                code="issue", journal=article.journal)
            issue.issue_type = issue_type
            issue.save()
            logger.info("Created new issue {}".format(issue))

        article.primary_issue = issue
        article.save()
        issue.articles.add(article)

        if date_published:
            article.date_published = date_published
            article.save()


def import_galleys(article, layout_dict, client):
    galleys = list()

    if layout_dict.get('galleys'):

        for galley in layout_dict.get('galleys'):
            logger.info(
                'Adding Galley with label {label}'.format(
                    label=galley.get('label')
                )
            )
            remote_file = client.fetch_file(
                galley.get("file"), galley.get("label"))
            galley_file = core_files.save_file_to_article(
                remote_file, article, article.owner, label=galley.get("label"))

            new_galley, c = core_models.Galley.objects.get_or_create(
                article=article,
                file=galley_file,
                defaults={"label": galley.get("label")},
            )
            if c:
                galleys.append(new_galley)

    return galleys


def calculate_article_stage(article_dict, article):

    if article_dict.get('publication') and article.date_published:
        stage = submission_models.STAGE_PUBLISHED
    elif article_dict.get("proofing"):
        stage = submission_models.STAGE_PROOFING
    elif article_dict.get("layout") and article_dict["layout"].get("galleys"):
        stage = submission_models.STAGE_TYPESETTING
    elif article_dict.get("copyediting"):
        stage = submission_models.STAGE_AUTHOR_COPYEDITING
    elif article_dict.get("review_file_url") or article_dict.get("reviews"):
        stage = submission_models.STAGE_UNDER_REVIEW
    else:
        stage = submission_models.STAGE_UNASSIGNED

    return stage


def get_or_create_article(article_dict, journal):
    """Get or create article, looking up by OJS ID or DOI"""
    date_started = timezone.make_aware(
        dateparser.parse(article_dict.get('date_submitted')))

    doi = article_dict.get("doi")
    ojs_id = article_dict["ojs_id"]

    if doi and identifiers_models.Ientifier.objects.filter(
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
        id_type="pubid",
        identifier=ojs_id,
        article__journal=journal,
    ).exists():
        article = identifiers_models.Identifier.objects.get(
            id_type="pubid",
            identifier=ojs_id,
            article__journal=journal,
        ).article
    else:
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
            id_type="pubid",
            identifier=ojs_id,
            article=article,
        )

    return article


def get_or_create_account(data, roles=None):
    """ Gets or creates an account for the given OJS user data"""
    try:
        account = core_models.Account.objects.get(
            email__iexact=data["email"])
    except core_models.Account.DoesNotExist:
        account = core_models.Account.objects.create(
            email=data.get('email'),
            first_name=data.get('first_name'),
            last_name=data.get('last_name'),
            institution=data.get('affiliation', ""),
            biography=data.get('bio'),
        )

    if data.get('country'):
        try:
            country = core_models.Country.objects.get(
                code=data.get('country'))
            account.country = country
            account.save()
        except core_models.Country.DoesNotExist:
            pass

    return account


def attempt_to_make_timezone_aware(datetime):
    if datetime:
        dt = dateparser.parse(datetime)
        return timezone.make_aware(dt)
    else:
        return None
