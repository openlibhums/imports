from dateutil import parser as dateparser
import os
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from django.core.files.base import ContentFile
from django.utils import timezone
import requests

from core import models as core_models, files as core_files
from journal import models as journal_models
from submission import models as submission_models
from identifiers import models as identifiers_models
from review import models as review_models
from utils import (
    models as utils_models,
    setting_handler,
    shared as utils_shared,
)
from utils import shared as utils_shared
from utils.logger import get_logger

logger = get_logger(__name__)


class OJSJanewayClient():
    PLUGIN_PATH = '/janeway'
    AUTH_PATH = '/login/signIn'
    HEADERS = {
        "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/39.0.2171.95 Safari/537.36"
    }
    SUPPORTED_STAGES = {
        'published',
        'in_editing',
        'in_review',
    }

    def __init__(self, journal_url, username=None, password=None, session=None):
        """"A Client for the OJS Janeway plugin API"""
        self.journal_url = journal_url
        self._auth_dict = {}
        self.session = session or requests.Session()
        self.session.headers.update(**self.HEADERS)
        self.authenticated = False
        if username and password:
            self._auth_dict = {
                'username': username,
                'password': password,
            }
            self.login()

    def fetch(self, request_url, headers=None, stream=False):
        response = self.session.get(
            request_url, headers=headers, stream=stream)
        return response

    def fetch_file(self, url, filename=None):
        response = self.fetch(url, stream=True)
        blob = response.content
        content_file = ContentFile(blob)
        if filename:
            _, extension = os.path.splitext(url)
            content_file.name = filename + extension
        return content_file

    def post(self, request_url, headers=None, body=None):
        if not headers:
            headers = {}
        response = self.session.post(request_url, headers=headers, data=body)
        return response

    def login(self, username=None, password=None):
        # Fetch Login page
        auth_url = self.journal_url + self.AUTH_PATH
        req_body = {
            "username": self._auth_dict.get("username") or self.username,
            "password": self._auth_dict.get("password") or self.password,
            "source": "",
        }
        req_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = self.post(auth_url, headers=req_headers, body=req_body)
        self.authenticated = True

    def get_articles(self, stage):
        if stage not in self.SUPPORTED_STAGES:
            raise NameError("Stage %s not supported", (stage))
        request_url = (
            self.journal_url
            + self.PLUGIN_PATH
            + "?%s" % urlencode({"request_type": stage})
        )
        response = self.fetch(request_url)
        data = response.json()
        for article in data:
            yield article


def import_articles(journal_url, ojs_username, ojs_password, journal):
    client = OJSJanewayClient(journal_url, ojs_username, ojs_password)
    review_articles = client.get_articles("published")
    for article in review_articles:
        create_article_with_review_content(article, journal, client)


def create_article_with_review_content(article_dict, journal, client):
    """Copied from core imports library, adjusted to use the client

    https://github.com/BirkbeckCTP/janeway/blob/ \
        e89886d3791d4eaba6b5bb7b0cf047473bca33fb/src/utils/importers/up.py#L580
    """
    date_started = timezone.make_aware(
        dateparser.parse(article_dict.get('date_submitted')))

    # Create a base article
    article =submission_models.Article(
        journal=journal,
        title=article_dict.get('title'),
        abstract=article_dict.get('abstract'),
        language=article_dict.get('language'),
        stage=submission_models.STAGE_UNDER_REVIEW,
        is_import=True,
        date_submitted=date_started,
    )

    article.save()

    # Check for editors and assign them as section editors.
    editors = article_dict.get('editors', [])

    for editor in editors:
        try:
            account = core_models.Account.objects.get(email=editor)
            account.add_account_role('section-editor', journal)
            review_models.EditorAssignment.objects.create(article=article, editor=account, editor_type='section-editor')
            logger.info(
                'Editor %s added to article %s' % (editor.email, article.pk))
        except Exception as e:
            logger.error('Editor account was not found.')
            logger.exception(e)

    # Add a new review round
    round = review_models.ReviewRound.objects.create(article=article, round_number=1)

    # Add keywords
    keywords = article_dict.get('keywords')
    if keywords:
        for keyword in keywords.split(';'):
            word, created = submission_models.Keyword.objects.get_or_create(
                word=keyword)
            article.keywords.add(word)

    # Add authors
    for author in article_dict.get('authors'):
        try:
            author_record = core_models.Account.objects.get(
                email=author.get('email'))
        except core_models.Account.DoesNotExist:
            author_record = core_models.Account.objects.create(
                email=author.get('email'),
                first_name=author.get('first_name'),
                last_name=author.get('last_name'),
                institution=author.get('affiliation', ""),
                biography=author.get('bio'),
            )

        # If we have a country, fetch its record
        if author.get('country'):
            try:
                country = core_models.Country.objects.get(code=author.get('country'))
                author_record.country = country
                author_record.save()
            except core_models.Country.DoesNotExist:
                pass
        # Add authors to m2m and create an order record
        article.authors.add(author_record)
        submission_models.ArticleAuthorOrder.objects.create(
            article=article,
            author=author_record,
            order=article.next_author_sort()
        )

        # Set the primary author
        article.owner = core_models.Account.objects.get(
            email=article_dict.get('correspondence_author'))
        article.correspondence_author = article.owner

        # Get or create the article's section
        try:
            section = submission_models.Section.objects.language().fallbacks(
                'en'
            ).get(journal=journal, name=article_dict.get('section'))
        except submission_models.Section.DoesNotExist:
            section = None

        article.section = section

        article.save()

    # Attempt to get the default review form
    form = setting_handler.get_setting(
        'general',
        'default_review_form',
        journal,
        create=True,
    ).processed_value

    if not form:
        try:
            form = review_models.ReviewForm.objects.filter(journal=journal)[0]
        except Exception:
            form = None
            logger.error(
                'You must have at least one review form for the journal before'
                ' importing.'
            )
            raise

    for review in article_dict.get('reviews'):
        try:
            reviewer = core_models.Account.objects.get(email=review.get('email'))
        except core_models.Account.DoesNotExist:
            reviewer = core_models.Account.objects.create(
                email=review.get('email'),
                first_name=review.get('first_name'),
                last_name=review.get('last_name'),
            )

        # Parse the dates
        date_requested = timezone.make_aware(dateparser.parse(review.get('date_requested')))
        date_due = timezone.make_aware(dateparser.parse(review.get('date_due')))
        date_complete = timezone.make_aware(dateparser.parse(review.get('date_complete'))) if review.get(
            'date_complete') else None
        date_confirmed = timezone.make_aware(dateparser.parse(review.get('date_confirmed'))) if review.get(
            'date_confirmed') else None

        # If the review was declined, setup a date declined date stamp
        review.get('declined')
        if review.get('declined') == '1':
            date_declined = date_confirmed
            date_accepted = None
            date_complete = date_confirmed
        else:
            date_accepted = date_confirmed
            date_declined = None

        new_review = review_models.ReviewAssignment.objects.create(
            article=article,
            reviewer=reviewer,
            review_round=round,
            review_type='traditional',
            visibility='double-blind',
            date_due=date_due,
            date_requested=date_requested,
            date_complete=date_complete,
            date_accepted=date_accepted,
            access_code=uuid.uuid4(),
            form=form
        )

        if review.get('declined') or review.get('recommendation'):
            new_review.is_complete = True

        if review.get('recommendation'):
            new_review.decision = map_review_recommendation(review.get('recommendation'))

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
    logger.info("Imported article with article ID %d" % article.pk)

    return article


