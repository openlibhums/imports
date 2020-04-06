from urllib.parse import urlencode

from bs4 import BeautifulSoup
import requests


class OJSJanewayClient():
    PLUGIN_PATH = '/janeway'
    AUTH_PATH = '/login/signIn'
    PUBLISHED_QS = urlencode({'request_type': 'published'})
    HEADERS = {
        "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/39.0.2171.95 Safari/537.36"
    }

    def __init__(self, journal_url, username=None, password=None):
        """"A Client for the OJS Janeway plugin API"""
        self.journal_url = journal_url
        self._auth_dict = {}
        self.session = requests.Session()
        self.session.headers.update(**self.HEADERS)
        self.authenticated = False
        if username and password:
            self._auth_dict = {
                'username': username,
                'password': password,
            }
            self.login()

    def fetch(self, request_url, headers=None):
        response = self.session.get(request_url)
        return response

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
        import pdb;pdb.set_trace()
        response = self.post(auth_url, headers=req_headers, body=req_body)
        self.authenticated = True

    def get_published_articles(self):
        request_url = (self.journal_url
            + self.PLUGIN_PATH
            + "?%s" % self.PUBLISHED_QS
        )
        response = self.fetch(request_url)
        return response


def import_articles(journal_url, ojs_username, ojs_password, journal):
    client = OJSJanewayClient(journal_url, ojs_username, ojs_password)
    content = client.get_published_articles()

