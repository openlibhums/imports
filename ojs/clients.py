import requests
import os
from django.core.files.base import ContentFile
from urllib.parse import urlencode


class OJSJanewayClient():
    PLUGIN_PATH = '/janeway'
    AUTH_PATH = '/login/signIn'
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
        return self.session.get(request_url, headers=headers, stream=stream)

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