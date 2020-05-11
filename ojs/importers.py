import uuid

from dateutil import parser as dateparser
from django.conf import settings
from django.utils import timezone

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

logger = get_logger(__name__)


REVIEW_RECOMMENDATION = {
    '2': 'minor_revisions',
    '3': 'major_revisions',
    '5': 'reject',
    '1': 'accept'
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


GALLEY_TYPES = {
    "PDF":  "pdf",
    "XML":  "xml",
    "HTML": "html",
}


def import_article_metadata(article_dict, journal, client):
    """ Creates or updates an article record given the OJS metadata"""
    article, created = get_or_create_article(article_dict, journal)
    if created:
        logger.debug("Created article %d" % article.pk)
    else:
        logger.debug("Updating article %d" % article.pk)

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
        for keyword in keywords:
            word, _ = submission_models.Keyword.objects.get_or_create(
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
        article.save()

    # Get or create the article's section
    section_name = article_dict.get('section', 'Article')
    section, _ = submission_models.Section.objects.language(
        settings.LANGUAGE_CODE
    ).get_or_create(journal=journal, name=section_name)

    article.section = section
    article.save()

    # Set the license
    license_url = article_dict.get("license", "")
    try:
        article.license = submission_models.Licence.objects.get(
                journal=article.journal,
                url=license_url,
        )
    except submission_models.Licence.DoesNotExist:
        try:
            article.license = submission_models.Licence.objects.get(
                    journal=article.journal,
                    short_name="Copyright",
            )
        except submission_models.Licence.DoesNotExist:
            logger.error("No license could be parsed from: %s" % license_url)
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
            if fetched_review_file:
                review_file = core_files.save_file_to_article(
                    fetched_review_file, article, reviewer,
                    label="Review File",
                )

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
    if manuscript:
        ms_file = core_files.save_file_to_article(
            manuscript, article, article.owner, label="Manuscript")
        article.manuscript_files.add(ms_file)

    # Get Supp Files
    if article_dict.get('supp_files'):
        for supp in article_dict.get('supp_files'):
            supp = client.fetch_file(supp["url"], supp["title"])
            if supp:
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
                    if fetched_final:
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
    """ Imports an article-issue relationship
    If the issue doesn't exist yet, it gets created
    """
    pub_data = article_dict.get("publication")
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
        pages = article_section_dict["pages"]
        # pages is a string describing a range: "3-19"
        # or just a string describing the start page: "3"
        if pages:
            if "-" in pages:
                start_page, _ = article_section_dict["pages"].split("-")
            else:
                start_page = pages
            try:
                article.page_numbers = int(start_page)
            except ValueError:
                logger.warning("Can't import pages value: %s" % pages)

        article.save()

        ordering, _ = journal_models.ArticleOrdering.objects.get_or_create(
            issue=issue,
            article=article,
            section=section,
        )
        ordering.order = order


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
                type=GALLEY_TYPES.get(galley.get("label", "other")),
                defaults={
                    "label": galley.get("label"),
                    "file": galley_file,
                },
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
    created = False
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


def get_or_create_account(data):
    """ Gets or creates an account for the given OJS user data"""
    try:
        account = core_models.Account.objects.get(
            email__iexact=data["email"])
    except core_models.Account.DoesNotExist:
        account = core_models.Account.objects.create(
            email=data.get('email'),
        )

    account.salutation = data.get("salutation")
    account.first_name = data.get('first_name')
    account.middle_name = data.get('middle_name')
    account.last_name = data.get('last_name')
    account.institution = data.get('affiliation', '')
    account.biography = data.get('bio')
    account.orcid = data.get("orcid")

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
        defaults={
            "date": date_published,
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


def attempt_to_make_timezone_aware(datetime):
    if datetime:
        dt = dateparser.parse(datetime)
        return timezone.make_aware(dt)
    else:
        return None
