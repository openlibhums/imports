import requests
import os
from django.core.files.base import ContentFile
from urllib.parse import urlencode, urlparse
from utils.logger import get_logger

from core.files import check_in_memory_mime

logger = get_logger(__name__)


class OJSJanewayClient():
    PLUGIN_PATH = '/janeway'
    AUTH_PATH = '/login/signIn'
    ISSUES_PATH = "/issues"
    USERS_PATH = "/users"
    METRICS_PATH = "/metrics"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/39.0.2171.95 Safari/537.36"
    }
    SUPPORTED_STAGES = {
        'published',
        'in_editing',
        'in_review',
    }

    def __init__(self, journal_url, user=None, password=None, session=None):
        """"A Client for the OJS Janeway plugin API"""
        self.journal_url = journal_url
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
            if not extension:
                _, extension = os.path.splitext(url)
            content_file.name = filename + extension
        else:
            content_file.name = os.path.basename(url)
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
        self.post(auth_url, headers=req_headers, body=req_body)
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

    def get_issues(self):
        request_url = (
            self.journal_url
            + self.PLUGIN_PATH
            + self.ISSUES_PATH
        )
        response = self.fetch(request_url)
        data = response.json()
        for issue in data:
            yield issue

    def get_users(self):
        request_url = (
            self.journal_url
            + self.PLUGIN_PATH
            + self.USERS_PATH
        )
        response = self.fetch(request_url)
        data = response.json()
        for user in data:
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
            + self.PLUGIN_PATH
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
    PLUGIN_PATH = '/jms/janeway'
    AUTH_PATH = '/author/login/'
    LOGIN_HEADERS = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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
        logger.debug("Setting CSRFTOKEN for url:%s " % url)
        response = self.fetch(url)


def strip_scheme(url):
    parsed = urlparse(url)
    scheme = "%s://" % parsed.scheme
    return parsed.geturl().replace(scheme, '', 1)
