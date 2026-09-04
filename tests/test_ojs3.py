import copy
from io import StringIO
from unittest import mock

import requests
from django.test import TestCase
from django.core.files.base import ContentFile

from core import models as core_models
from core import workflow as core_workflow
from identifiers import models as id_models
from journal import models as journal_models
from utils.testing import helpers

from plugins.imports import ojs
from plugins.imports.ojs import clients, ojs3_importers


def create_import_workflow(journal):
    """ Builds a workflow covering every stage the OJS3 importer logs

    create_default_workflow only installs the first four base elements, which
    leaves no element for STAGE_TYPESETTING. The importer logs against that
    stage for OJS submissions sat in production.
    """
    workflow = core_workflow.create_default_workflow(journal)
    for index, element in enumerate(core_models.BASE_ELEMENTS):
        workflow_element, _ = core_models.WorkflowElement.objects.get_or_create(
            journal=journal,
            element_name=element["name"],
            handshake_url=element["handshake_url"],
            stage=element["stage"],
            jump_url=element["jump_url"],
            article_url=element["article_url"],
            defaults={"order": index},
        )
        workflow.elements.add(workflow_element)
    return workflow


def build_response(content=b"", status_code=200, url="http://ojs.test/file"):
    """ Builds a requests.Response without touching the network """
    response = requests.Response()
    response.status_code = status_code
    response._content = content
    response.url = url
    return response



class OJS3ImportUsers(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.journal, *_ = helpers.create_journals()
        helpers.create_roles(["editor", "author"])

    def test_import_user(self):
        mock_client = MockOJS3Client()
        ojs.import_ojs3_users(mock_client, self.journal)
        email = mock_client.USER_DICT["email"]

        self.assertTrue(
            core_models.Account.objects.filter(email=email).exists()
        )

    def test_import_user_role(self):
        mock_client = MockOJS3Client()
        ojs.import_ojs3_users(mock_client, self.journal)
        email = mock_client.USER_DICT["email"]
        account = core_models.Account.objects.get(email=email)

        self.assertTrue(
            core_models.AccountRole.objects.filter(
                user=account,
                role__slug="editor",
            ).exists()
        )

class OJS3ImportArticles(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.journal, *_ = helpers.create_journals()
        helpers.create_roles(["editor", "author"])

    def test_import_article(self):
        mock_client = MockOJS3Client()
        ojs.import_ojs3_articles(mock_client, self.journal)

        self.assertEqual(
            id_models.Identifier.objects.get(
                id_type="doi", identifier='10.0001/test'
            ).article.get_identifier("ojs_id"),
            '17660',
        )

    def test_import_article_languages(self):
        mock_client = MockOJS3Client()
        ojs.import_ojs3_articles(mock_client, self.journal)

        article = id_models.Identifier.objects.get(
            id_type="doi", identifier='10.0001/test'
        ).article
        #self.assertEqual(article.title_de, "titel")


class OJS3ImportAuthorAssignments(TestCase):
    """ OJS submissions can be served without an "authors" key """

    @classmethod
    def setUpTestData(cls):
        cls.journal, *_ = helpers.create_journals()
        helpers.create_roles(["editor", "author"])
        create_import_workflow(cls.journal)
        cls.article = helpers.create_article(cls.journal)
        cls.article_dict_no_authors = {"id": 17660}
        cls.article_dict_empty_authors = {"id": 17660, "authors": []}

    def test_missing_authors_key_does_not_raise(self):
        ojs3_importers.import_author_assignments(
            self.article, self.article_dict_no_authors,
        )

    def test_empty_authors_list_does_not_raise(self):
        ojs3_importers.import_author_assignments(
            self.article, self.article_dict_empty_authors,
        )

    def test_missing_authors_key_does_not_abort_article_import(self):
        mock_client = MockOJS3Client()
        ojs.import_ojs3_articles(mock_client, self.journal, raise_on_exc=True)

        article = id_models.Identifier.objects.get(
            id_type="doi", identifier='10.0001/test',
        ).article
        self.assertEqual(article.galley_set.count(), 1)


class OJS3APIClientFetchFile(TestCase):
    """ Empty responses must not be turned into zero byte files """

    @classmethod
    def setUpTestData(cls):
        cls.ojs_client = clients.OJS3APIClient("http://ojs.test/journal")
        cls.url = "http://ojs.test/journal/article/download/1/1"

    def test_empty_response_returns_none(self):
        with mock.patch.object(
            self.ojs_client.session, "get",
            return_value=build_response(b"", url=self.url),
        ):
            self.assertIsNone(self.ojs_client.fetch_file(self.url))

    def test_error_response_returns_none(self):
        with mock.patch.object(
            self.ojs_client.session, "get",
            return_value=build_response(b"", 404, url=self.url),
        ):
            self.assertIsNone(self.ojs_client.fetch_file(self.url))

    def test_populated_response_returns_content_file(self):
        with mock.patch.object(
            self.ojs_client.session, "get",
            return_value=build_response(b"content", url=self.url),
        ):
            content_file = self.ojs_client.fetch_file(self.url)

        self.assertEqual(content_file.read(), b"content")


class OJS3ImportEmptyArticleGalleys(TestCase):
    """ A galley whose file is missing on OJS must be skipped """

    @classmethod
    def setUpTestData(cls):
        cls.journal, *_ = helpers.create_journals()
        helpers.create_roles(["editor", "author"])
        create_import_workflow(cls.journal)

    def test_empty_galley_file_creates_no_galley(self):
        mock_client = MockOJS3EmptyFileClient()
        ojs.import_ojs3_articles(mock_client, self.journal, raise_on_exc=True)

        article = id_models.Identifier.objects.get(
            id_type="doi", identifier='10.0001/test',
        ).article
        self.assertFalse(article.galley_set.exists())

    def test_empty_galley_file_creates_no_file(self):
        mock_client = MockOJS3EmptyFileClient()
        ojs.import_ojs3_articles(mock_client, self.journal, raise_on_exc=True)

        article = id_models.Identifier.objects.get(
            id_type="doi", identifier='10.0001/test',
        ).article
        self.assertFalse(
            core_models.File.objects.filter(article_id=article.pk).exists()
        )


class OJS3ImportIssueGalleys(TestCase):
    """ An issue galley missing on OJS must be skipped """

    ISSUE_DICT = {
        "articles": [],
        "coverImageUrl": {},
        "datePublished": "2021-02-23",
        "description": {"en_US": "description"},
        "galleys": [{"id": 4321}],
        "id": 2477,
        "isCurrent": False,
        "number": "1",
        "sections": [],
        "title": {"en_US": "Issue Title"},
        "volume": 1,
        "year": 2021,
    }

    @classmethod
    def setUpTestData(cls):
        cls.journal, *_ = helpers.create_journals()
        helpers.create_roles(["editor", "author"])

    def test_empty_issue_galley_creates_no_issue_galley(self):
        mock_client = MockOJS3EmptyFileClient()
        issue = ojs3_importers.import_issue(
            mock_client, self.journal, copy.deepcopy(self.ISSUE_DICT),
        )

        self.assertFalse(
            journal_models.IssueGalley.objects.filter(issue=issue).exists()
        )

    def test_populated_issue_galley_is_imported(self):
        mock_client = MockOJS3Client()
        issue = ojs3_importers.import_issue(
            mock_client, self.journal, copy.deepcopy(self.ISSUE_DICT),
        )

        self.assertTrue(
            journal_models.IssueGalley.objects.filter(issue=issue).exists()
        )


class MockOJS3Client():
    USER_DICT = {
        "affiliation": {
            "en_US": "affiliation",
        },
        "authId": None,
        "authString": None,
        "billingAddress": None,
        "biography": None,
        "country": "BE",
        "dateLastLogin": "2019-11-02 17:42:07",
        "dateRegistered": "2019-11-02 17:42:07",
        "dateValidated": None,
        "disabled": False,
        "disabledReason": None,
        "email": "ojs3@email.com",
        "familyName": {
            "en_US": "last_name",
        },
        "fullName": "somename",
        "givenName": {
            "en_US": "first_name",
        },
        "groups": [
            {
            "id": 357,
            "name": {
                "en_US": "Editor",
            },
            "abbrev": {
                "en_US": "Editor",
            },
            "roleId": 16,
            "showTitle": False,
            "permitSelfRegistration": True,
            "permitMetadataEdit": False,
            "recommendOnly": False
            }
        ],
        "id": 8877,
        "interests": [],
        "mailingAddress": None,
        "mustChangePassword": False,
        "orcid": "0000-0000-0000-0001",
        "phone": None,
        "signature": None,
        "url": None,
        "userName": "someusername"
    }
    PUBLISHED_ARTICLE = {
        '_href': 'url',
        'contextId': 26,
        'currentPublicationId': 15275,
        'dateLastActivity': '2021-03-01 11:01:48',
        'dateSubmitted': '2021-02-23 14:10:52',
        'id': 17660,
        'lastModified': '2021-03-01 11:04:46',
        'publications': [{'_href': 'url',
                        'authorsString': '',
                        'authorsStringShort': 'author et al',
                        'categoryIds': [],
                        'coverImage': {'en_US': None},
                        'datePublished': '2021-02-23',
                        'doiSuffix': None,
                        'fullTitle': {'en_US': 'title', 'en_DE': 'titel'},
                        'galleys': [{'doiSuffix': None,
                                    'file': {'_href': 'url',
                                                'assocId': 15052,
                                                'assocType': 521,
                                                'caption': None,
                                                'copyrightOwner': None,
                                                'createdAt': '2021-02-23 14:17:46',
                                                'creator': {'en_US': ''},
                                                'credit': None,
                                                'dateCreated': None,
                                                'dependentFiles': [],
                                                'description': {'en_US': ''},
                                                'documentType': 'pdf',
                                                'doiSuffix': None,
                                                'fileId': 31327,
                                                'fileStage': 10,
                                                'genreId': 276,
                                                'id': 34447,
                                                'language': None,
                                                'locale': 'en_US',
                                                'mimetype': 'application/pdf',
                                                'name': {'en_US': 'file.pdf'},
                                                'path': 'somepath',
                                                'pub-id::doi': None,
                                                'publisher': {'en_US': ''},
                                                'revisions': [],
                                                'source': {'en_US': ''},
                                                'sourceSubmissionFileId': None,
                                                'sponsor': {'en_US': ''},
                                                'subject': {'en_US': ''},
                                                'submissionId': 17660,
                                                'terms': None,
                                                'updatedAt': '2021-02-23 14:17:46',
                                                'uploaderUserId': 9309,
                                                'url': 'url',
                                                'viewable': False},
                                    'id': 15052,
                                    'isApproved': True,
                                    'label': 'PDF',
                                    'locale': 'en_US',
                                    'pub-id::doi': None,
                                    'pub-id::publisher-id': None,
                                    'publicationId': 15275,
                                    'seq': 0,
                                    'submissionFileId': 34447,
                                    'urlPublished': 'url',
                                    'urlRemote': ''}],
                        'id': 15275,
                        'locale': 'en_US',
                        'pages': '1-5',
                        'prefix': {'en_US': ''},
                        'primaryContactId': None,
                        'pub-id::doi': '10.0001/test',
                        'pub-id::publisher-id': None,
                        'sectionId': 169,
                        'status': 3,
                        'submissionId': 17660,
                        'subtitle': {'en_US': ''},
                        'title': {'en_US': 'title'},
                        'urlPublished': 'url',
                        'version': 1}],
        'reviewAssignments': [],
        'reviewRounds': [],
        'stageId': 5,
        'stages': [{'currentUserAssignedRoles': [],
                    'files': {'count': 0},
                    'id': 1,
                    'isActiveStage': False,
                    'label': 'Submission',
                    'queries': []},
                {'currentUserAssignedRoles': [],
                    'files': {'count': 0},
                    'id': 3,
                    'isActiveStage': False,
                    'label': 'Review',
                    'queries': []},
                {'currentUserAssignedRoles': [],
                    'files': {'count': 0},
                    'id': 4,
                    'isActiveStage': False,
                    'label': 'Copyediting',
                    'queries': []},
                {'currentUserAssignedRoles': [],
                    'files': {'count': 0},
                    'id': 5,
                    'isActiveStage': True,
                    'label': 'Production',
                    'queries': []}],
        'status': 3,
        'statusLabel': 'Published',
        'submissionProgress': 0,
    }
    PUBLICATION = {
        '_href': '',
        'abstract': {'en_US': 'abstract'},
        'accessStatus': 0,
        'authors': [{'affiliation': {'en_US': 'affiliation'},
                    'email': 'ojs3@email.com',
                    'familyName': {'en_US': 'family_name'},
                    'givenName': {'en_US': 'author_name'},
                    'id': 21434,
                    'includeInBrowse': True,
                    'orcid': '',
                    'preferredPublicName': {'en_US': ''},
                    'publicationId': 15275,
                    'seq': 2,
                    'submissionLocale': 'en_US',
                    'userGroupId': 388}],
        'authorsString': 'the authors',
        'authorsStringShort': 'authors et al.',
        'categoryIds': [],
        'citations': [],
        'citationsRaw': None,
        'copyrightHolder': {'en_US': 'author et all'},
        'copyrightYear': 2021,
        'coverImage': {'en_US': None},
        'coverage': {'en_US': ''},
        'datePublished': '2021-02-23',
        'disciplines': {'en_US': []},
        'doiSuffix': None,
        'fullTitle': {'en_US': 'title'},
        'galleys': [{'doiSuffix': None,
                    'file': {'_href': 'url',
                            'assocId': 15052,
                            'assocType': 521,
                            'caption': None,
                            'copyrightOwner': None,
                            'createdAt': '2021-02-23 14:17:46',
                            'creator': {'en_US': ''},
                            'credit': None,
                            'dateCreated': None,
                            'dependentFiles': [],
                            'description': {'en_US': ''},
                            'documentType': 'pdf',
                            'doiSuffix': None,
                            'fileId': 31327,
                            'fileStage': 10,
                            'genreId': 276,
                            'id': 34447,
                            'language': None,
                            'locale': 'en_US',
                            'mimetype': 'application/pdf',
                            'name': {'en_US': 'test.pdf'},
                            'path': 'path.pdf',
                            'pub-id::doi': None,
                            'publisher': {'en_US': ''},
                            'revisions': [],
                            'source': {'en_US': ''},
                            'sourceSubmissionFileId': None,
                            'sponsor': {'en_US': ''},
                            'subject': {'en_US': ''},
                            'submissionId': 17660,
                            'terms': None,
                            'updatedAt': '2021-02-23 14:17:46',
                            'uploaderUserId': 9309,
                            'url': 'url',
                            'viewable': False},
                    'id': 15052,
                    'isApproved': True,
                    'label': 'PDF',
                    'locale': 'en_US',
                    'pub-id::doi': None,
                    'pub-id::publisher-id': None,
                    'publicationId': 15275,
                    'seq': 0,
                    'submissionFileId': 34447,
                    'urlPublished': '',
                    'urlRemote': ''}],
        'hideAuthor': None,
        'id': 15275,
        'issueId': 2477,
        'keywords': {'en_US': []},
        'languages': {'en_US': []},
        'lastModified': '2021-03-01 11:04:46',
        'licenseUrl': None,
        'locale': 'en_US',
        'pages': '1-5',
        'prefix': {'en_US': ''},
        'primaryContactId': None,
        'pub-id::doi': '10.0001/test',
        'pub-id::publisher-id': None,
        'rights': {'en_US': ''},
        'sectionId': 169,
        'seq': 2,
        'source': {'en_US': ''},
        'status': 3,
        'subjects': {'en_US': []},
        'submissionId': 17660,
        'subtitle': {'en_US': ''},
        'supportingAgencies': {'en_US': []},
        'title': {'en_US': 'title'},
        'type': {'en_US': ''},
        'urlPath': None,
        'urlPublished': 'url',
        'version': 1
    }

    def get_users(self):
        yield self.USER_DICT

    def get_articles(self):
        yield copy.deepcopy(self.PUBLISHED_ARTICLE)

    def get_publication(self, *args, **kwargs):
        return copy.deepcopy(self.PUBLICATION)

    def fetch_file(self, *args, **kwargs):
        return ContentFile(b'test', name='test.pdf')

    def get_issue_galley(self, *args, **kwargs):
        return ContentFile(b'test', name='issue.pdf')


class MockOJS3EmptyFileClient(MockOJS3Client):
    """ Mimics an OJS install whose galley files are missing from disk

    File fetches run through the real OJS3APIClient file handling so that the
    empty response is dealt with where the importer would deal with it, rather
    than being short circuited by the mock.
    """

    def __init__(self):
        self.api_client = clients.OJS3APIClient("http://ojs.test/journal")
        self.api_client.session = mock.Mock()
        self.api_client.session.get.return_value = build_response(b"")

    def fetch_file(self, url="http://ojs.test/file", *args, **kwargs):
        return self.api_client.fetch_file(url, *args, **kwargs)

    def get_issue_galley(self, issue_id, galley_id):
        return self.api_client.get_issue_galley(issue_id, galley_id)
