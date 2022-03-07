from django.test import TestCase
from utils.testing import helpers
from utils.install import update_issue_types
from plugins.imports.tests.test_utils import CSV_DATA_1, run_import, dict_from_csv_string
from plugins.imports import views, urls
from submission import models as submission_models
from journal import models as journal_models
from django.http import HttpRequest
from core import logic as core_logic
from rest_framework import routers
from django.core.urlresolvers import reverse
from django.shortcuts import redirect
from utils import shared as utils_shared

class TestViews(TestCase):

    @classmethod
    def setUpTestData(cls):

        cls.press = helpers.create_press()
        cls.journal_one, cls.journal_two = helpers.create_journals()
        cls.journal_one.workflow()
        issue_type = journal_models.IssueType.objects.get_or_create(
            journal=cls.journal_one,
            code='issue'
        )
        cls.test_user = helpers.create_user(
            username='unrealperson12@example.com',
        )
        cls.test_user_password = utils_shared.generate_password()
        cls.test_user.set_password(cls.test_user_password)
        cls.test_user.is_staff = True
        cls.mock_request = HttpRequest()
        cls.mock_request.user = cls.test_user
        cls.mock_request.journal = cls.journal_one
        for plugin_element_name in ['Typesetting Plugin']:
            element = core_logic.handle_element_post(
                cls.journal_one.workflow(),
                plugin_element_name,
                cls.mock_request,
            )
            cls.journal_one.workflow().elements.add(element)

    def test_export_stages(self):
        router = routers.DefaultRouter()
        router.register(r'exportfiles', views.ExportFilesViewSet, basename='exportfile')

        csv_data = dict_from_csv_string(CSV_DATA_1)
        for stage in [
            'Unassigned',
            'Editor Copyediting',
            'typesetting_plugin',
            'pre_publication',
            'Published'
        ]:
            csv_data[1]['Stage'] = stage
            run_import(csv_data, owner=self.test_user)

        from nose.tools import set_trace; set_trace()

        login = self.client.login(
            username='unrealperson12@example.com',
            password=self.test_user_password,
        )


        response = self.client.get(
            redirect(
                reverse(
                    'import_export_articles_all',
                    current_app = 'imports',
                    urlconf=urls,
                )
            )
        )
        self.assertEqual(response.status_code, 200)
