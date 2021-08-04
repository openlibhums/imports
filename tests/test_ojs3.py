from django.test import TestCase

from core import models as core_models
from utils.testing import helpers

from plugins.imports import ojs



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

    def get_users(self):
        yield self.USER_DICT


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
