import os
import re
from urllib import parse as urlparse

import requests
from django.core.files.base import ContentFile
from utils.logger import get_logger

from core.files import check_in_memory_mime

logger = get_logger(__name__)

class PaginatedResults():
    OFFSET_KEY = ""
    PAGE_KEY = ""
    RESULTS_KEY = None

    def __init__(self, url, client, per_page=20, **client_params):
        """ An iterator that yields results from an API using pagination
        :param URL: URL of the API endpoint.
        :param client: The request client to use for fetching results.
        :param per_page: Number of results to be fetched per page.
        :param key: Optional attribute name from which to get the results.
            To be used if the api doesnt return an array but an object like
            {"results": [...]}
        """
        self._page = None
        self._per_page = per_page
        self._url = url
        self._client = client
        self._results = iter([])
        self._client_params = client_params
        self._cached = None

    def __iter__(self):
        if self._results is None:
            self.results = self._fetch_results
        return self

    def __next__(self):
        try:
            return next(self._results)
        except StopIteration:
            self._fetch_results()
            return next(self)

    def _next_page(self):
        if self._page == None:
            self._page = 1
        else:
            self._page += 1

    def _fetch_results(self):
        self._next_page()
        url = self.build_url(self._url, self._page, self._per_page)
        data = self._client(url, **self._client_params).json()
        if data:
            if self.RESULTS_KEY:
                data = data.get(self.RESULTS_KEY, [])
        if not data:
            raise StopIteration
        if self._cached and self._cached == data:
            # There is no out of bounds error, API returns last results again
            raise StopIteration
        self._cached = data
        self._results = iter(data)

    @classmethod
    def build_url(cls, url, page, offset):
        params = {cls.PAGE_KEY: page, cls.OFFSET_KEY: offset}
        url_parts = list(urlparse.urlparse(url))
        query = dict(urlparse.parse_qsl(url_parts[4]))
        query.update(params)
        url_parts[4] = urlparse.urlencode(query)

        return urlparse.urlunparse(url_parts)
        

class OJS2PaginatedResults(PaginatedResults):
    OFFSET_KEY = "limit"
    PAGE_KEY = "page"


class OJS3PaginatedResults(PaginatedResults):
    OFFSET_KEY = "count"
    PAGE_KEY = "offset"
    RESULTS_KEY = "items"

    def _next_page(self):
        """Calculate next page parameter for the next request
        OJS 3 uses an offset rather than a page number, so we calculate the next
        page number as current page + count of items returned per page
        e.g with a count of 10, to get page 2 we set the offset to  0 + 10
        """
        if self._page == None:
            self._page = 0 # We start at 0 because it is an offset not a page
        else:
            self._page += self._per_page


class OJSBaseClient():
    API_PATH = ''  # Path to the OJS API to be consumed
    AUTH_PATH = '/login/signIn' # Path where the auth details should be posted
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/39.0.2171.95 Safari/537.36"
    }  # Base headers to include in every request
    LOGIN_HEADERS = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    def __init__(self, journal_url, user=None, password=None, session=None):
        """"A Client for consumption of OJS APIs"""
        self.journal_url = journal_url
        self.base_url = urlparse.urlunsplit(
            urlparse.urlsplit(journal_url)._replace(path="/")
        )
        self._auth_dict = {}
        self.session = session or requests.Session()
        self.session.headers.update(**self.HEADERS)
        self.authenticated = False
        if user and password:
            self._auth_dict = {
                'username': user,
                'password': password,
            }
            self.login()

    def login(self, username=None, password=None):
        # Fetch Login page
        auth_url = self.journal_url + self.AUTH_PATH
        req_body = {
            "username": self._auth_dict.get("username") or self.username,
            "password": self._auth_dict.get("password") or self.password,
            "source": "",
        }
        req_headers = self.LOGIN_HEADERS
        self.post(auth_url, headers=req_headers, body=req_body)
        self.authenticated = True


class OJSJanewayClient(OJSBaseClient):
    API_PATH = '/janeway'
    ISSUES_PATH = "/issues"
    COLLECTIONS_PATH = "/collections"
    SECTIONS_PATH = "/sections"
    USERS_PATH = "/users"
    METRICS_PATH = "/metrics"
    SUBMISSION_PATH = '/editor/submission/%s'
    SUPPORTED_STAGES = {
        'published',
        'in_editing',
        'in_review',
        'unassigned',
    }


    def fetch(self, request_url, headers=None, stream=False):
        resp = self.session.get(request_url, headers=headers, stream=stream)
        if not resp.ok:
            resp.raise_for_status()
        return resp

    def fetch_file(self, url, filename=None, extension=None, exc_mimes=None):
        """ Fetches  file from given URL
        :param url: The URL from where to fetch the file
        :param filename (optional): A name for the fetched file
        :param extension (optional): An extension override for the fetched file
        :param exc_mimes (optional): Set of mimes. If the fetched file is of
            matches one of these, it is discarded.
        :return: django.core.files.base.ContentFile or None
        """
        try:
            response = self.fetch(url, stream=True)
        except requests.exceptions.HTTPError as e:
            logger.error(e)
            return
        response_filename = get_filename_from_headers(response)
        blob = response.content
        content_file = ContentFile(blob)
        if exc_mimes:
            mime = check_in_memory_mime(content_file)
            if mime in exc_mimes:
                logger.info(
                    "Fetched file from %s ignored: %s in %s",
                    response.url, mime, exc_mimes,
                )
                return None
        if filename:
            if len(filename) >= 60:
                filename = filename[:60]
            if not extension and response_filename:
                _, extension = os.path.splitext(response_filename)
            elif not extension:
                _, extension = os.path.splitext(url)
            content_file.name = filename + extension
        elif response_filename:
            content_file.name = os.path.basename(url)
        return content_file

    def post(self, request_url, headers=None, body=None):
        if not headers:
            headers = {}
        response = self.session.post(request_url, headers=headers, data=body)
        return response


    def get_article(self, ojs_id):
        request_url = (
            self.journal_url
            + self.API_PATH
            + "?%s" % urlparse.urlencode({"article_id": ojs_id})
        )
        response = self.fetch(request_url)
        data = response.json()
        if data:
            return data[0]
        return None

    def get_articles(self, stage):
        if stage not in self.SUPPORTED_STAGES:
            raise NameError("Stage %s not supported", (stage))
        request_url = (
            self.journal_url
            + self.API_PATH
            + "?%s" % urlparse.urlencode({"request_type": stage})
        )
        client = self.fetch
        paginator = OJS2PaginatedResults(request_url, client)
        for article in paginator:
            yield article

    def get_issues(self):
        request_url = (
            self.journal_url
            + self.API_PATH
            + self.ISSUES_PATH
        )
        response = self.fetch(request_url)
        data = response.json()
        for issue in data:
            yield issue

    def get_collections(self):
        request_url = (
            self.journal_url
            + self.API_PATH
            + self.COLLECTIONS_PATH
        )
        response = self.fetch(request_url)
        data = response.json()
        for collection in data:
            yield collection

    def get_sections(self):
        request_url = (
            self.journal_url
            + self.API_PATH
            + self.SECTIONS_PATH
        )
        response = self.fetch(request_url)
        data = response.json()
        for section in data:
            yield section

    def get_users(self):
        request_url = (
            self.journal_url
            + self.API_PATH
            + self.USERS_PATH
        )
        response = self.fetch(request_url)
        data = response.json()
        client = self.fetch
        paginator = OJS2PaginatedResults(request_url, client)
        for user in paginator:
            yield user

    def get_metrics(self):
        """ Retrievesd the metrics as exposed by the Janeway Plugin for OJS
        :return: A mapping from metric type to a list of ojs ids and metric
            values e.g:
            {"views": [
                {"id": "12345",
                "count": "419"}
            ],
            "downloads": [
                {"id": "12345",
                "count": "235"}
            ]}
        """
        request_url = (
            self.journal_url
            + self.API_PATH
            + self.METRICS_PATH
        )
        response = self.fetch(request_url)
        data = response.json()

        return data


class UPJanewayClient(OJSJanewayClient):
    """ A client for interacting with UPs JMS which is OJS based

    JMS is based on OJS 2.4.3. All endpoints are compatible with
    the implementation of the OJSClient except for metrics. The
    other deviation is the authentication system which is not OJS
    based, although an OJS session can be retrieved.
    """
    API_PATH = '/jms/janeway'
    AUTH_PATH = '/author/login/'
    SUBMISSION_PATH = '/jms/editor/submission/%s'

    def login(self, username=None, password=None):
        # Fetch Login page
        auth_url = self.journal_url + self.AUTH_PATH
        self.set_csrftoken(auth_url)
        req_body = {
            "username": self._auth_dict.get("username") or username,
            "password": self._auth_dict.get("password") or password,
            "login": 'login',
            'csrfmiddlewaretoken': self.session.cookies["csrftoken"],
        }
        req_headers = dict(
            self.LOGIN_HEADERS,
            Host=strip_scheme(self.journal_url),
            Referer=auth_url,
        )
        self.post(auth_url, headers=req_headers, body=req_body)
        self.authenticated = True

    def set_csrftoken(self, url):
        """ Set the CSRF token cookie for the session
        Fetches the URL containing the form so that the token gets set by
        the request session handler.
        :param url: The URL for which the CSRFTOKEN needs setting
        """
        logger.debug("Setting CSRFTOKEN for url:%s " % url)
        self.fetch(url)


def strip_scheme(url):
    parsed = urlparse.urlparse(url)
    scheme = "%s://" % parsed.scheme
    return parsed.geturl().replace(scheme, '', 1)


def get_filename_from_headers(response):
    try:
        header = response.headers['content-disposition']
        return re.findall("filename=(.+)", header)[0]
    except KeyError:
        logger.debug("No content-disposition header")
    except IndexError:
        logger.debug("No Filename provided in headers")
    return None


class OJS3APIClient(OJSBaseClient):
    API_PATH = '/api/v1'
    AUTH_PATH = '/login/signIn'
    USERS_PATH = "/users"
    SUBMISSIONS_PATH = '/submissions/%s'
    ISSUES_PATH = '/issues/%s'
    ISSUE_GALLEY_PATH = "/issue/download/{issue}/{galley}"
    PUBLICATIONS_PATH = SUBMISSIONS_PATH + '/publications/%s'
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/39.0.2171.95 Safari/537.36"
    }

    # Submission status codes from OJS 3
    STATUS_QUEUED = 1
    STATUS_SCHEDULED = 2
    STATUS_PUBLISHED = 3
    STATUS_DECLINED = 4

    def fetch(self, request_url, headers=None, stream=False):
        resp = self.session.get(request_url, headers=headers, stream=stream)
        if not resp.ok:
            resp.raise_for_status()
        return resp

    def fetch_file(self, url, filename=None, extension=None, exc_mimes=None):
        """ Fetches  file from given URL
        :param url: The URL from where to fetch the file
        :param filename (optional): A name for the fetched file
        :param extension (optional): An extension override for the fetched file
        :param exc_mimes (optional): Set of mimes. If the fetched file is of
            matches one of these, it is discarded.
        :return: django.core.files.base.ContentFile or None
        """
        try:
            response = self.fetch(url, stream=True)
        except requests.exceptions.HTTPError as e:
            logger.error(e)
            return
        response_filename = get_filename_from_headers(response)
        blob = response.content
        content_file = ContentFile(blob)
        if exc_mimes:
            mime = check_in_memory_mime(content_file)
            if mime in exc_mimes:
                logger.info(
                    "Fetched file from %s ignored: %s in %s",
                    response.url, mime, exc_mimes,
                )
                return None
        if filename:
            if len(filename) >= 60:
                filename = filename[:60]
            if not extension and response_filename:
                _, extension = os.path.splitext(response_filename)
            elif not extension:
                _, extension = os.path.splitext(url)
            content_file.name = filename + extension
        elif response_filename:
            content_file.name = os.path.basename(url)
        return content_file

    def post(self, request_url, headers=None, body=None):
        if not headers:
            headers = {}
        response = self.session.post(request_url, headers=headers, data=body)
        return response

    def get_article(self, ojs_id):
        request_url = (
            self.journal_url
            + self.API_PATH
            + "?%s" % urlparse.urlencode({"article_id": ojs_id})
        )
        response = self.fetch(request_url)
        data = response.json()
        if data:
            return data[0]
        return None

    def get_articles(self):
        request_url = (
            self.journal_url
            + self.API_PATH
            + self.SUBMISSIONS_PATH % ''
        )
        client = self.fetch
        paginator = OJS3PaginatedResults(request_url, client)
        for i, article in enumerate(paginator):
            yield article

    def get_publication(self, ojs_id, publication_id):
        request_url = (
            self.journal_url
            + self.API_PATH
            + self.PUBLICATIONS_PATH % (ojs_id, publication_id)
        )
        response = self.fetch(request_url)
        return response.json()

    def get_issues(self):
        request_url = (
            self.journal_url
            + self.API_PATH
            + self.ISSUES_PATH % ''
        )
        client = self.fetch
        paginator = OJS3PaginatedResults(request_url, client)
        for i, issue in enumerate(paginator):
            # The issue endpoint for each issue object provides more data
            yield self.get_issue(issue["id"])

    def get_issue(self, ojs_issue_id):
        request_url = (
            self.journal_url
            + self.API_PATH
            + self.ISSUES_PATH % (ojs_issue_id)
        )
        response = self.fetch(request_url)
        return response.json()

    def get_issue_galley(self, issue_id, galley_id):
        """ Fetch an issue galley from its URL (not from the rest API)
        It seems the REST API won't return URLS or file paths for issue galleys,
        instead we construct the regular download path from the issue and 
        :param issue_id: The OJS ID of the issue
        :param galley_id: The OJS ID of the issue's galley
        :return: A django file wrapping the galley file or None
        """
        request_url = (
            self.journal_url
            + self.ISSUE_GALLEY_PATH.format(issue=issue_id, galley=galley_id)
        )

        return self.fetch_file(request_url)

    def get_users(self):
        request_url = (
            self.journal_url
            + self.API_PATH
            + self.USERS_PATH
        )
        response = self.fetch(request_url)
        data = response.json()
        for user in data:
            yield user
