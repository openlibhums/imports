from django.test import TestCase


class OJS3ImportTestCase(TestCase):

    def test_import_user(self)
        email = "ojs3@email.com"
        affiliation = "affiliation"
        first_name = "first name"
        last_name = "last name"
        user_dict = {
            "affiliation": {
                "en_US": affiliation,
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
            "email": email,
            "familyName": {
                "en_US": last_name,
            },
            "fullName": "somename",
            "givenName": {
                "en_US": first_name,
            },
            "groups": [
                {
                "id": 357,
                "name": {
                    "en_US": "Reader",
                    "fr_FR": "Lecteur",
                    "nl_NL": "Lezer"
                },
                "abbrev": {
                    "en_US": "Read",
                    "fr_FR": "Lect",
                    "nl_NL": "Read"
                },
                "roleId": 1048576,
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
            "orcid": None,
            "phone": None,
            "signature": None,
            "url": None,
            "userName": "someusername"
        }
