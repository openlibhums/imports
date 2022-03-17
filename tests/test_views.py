from django.test import TestCase, RequestFactory, override_settings
from core import urls
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
from django.core.management import call_command
from django.contrib.contenttypes.models import ContentType
import requests

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
        cls.test_user = helpers.create_editor(cls.journal_one)
        cls.test_user.is_staff = True
        cls.test_user.is_active = True
        cls.test_user.save()

#         cls.factory = RequestFactory()

        cls.plugin_request = HttpRequest()
        cls.plugin_request.journal = cls.journal_one
        for plugin_element_name in ['Typesetting Plugin']:
            element = core_logic.handle_element_post(
                cls.journal_one.workflow(),
                plugin_element_name,
                cls.plugin_request,
            )
            cls.journal_one.workflow().elements.add(element)

        router = routers.DefaultRouter()
        router.register(r'exportfiles', views.ExportFilesViewSet, basename='exportfile')

    @override_settings(URLCONFIG='domain')
    def test_export_stages(self):

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

#         request = self.factory.get('/plugins/imports/articles/all/')
#         self.client.force_login(self.test_user)
#         request.user = self.test_user
#         request.journal = self.journal_one
#         request.press = self.press
#         request.site_type = self.journal_one
#         request.model_content_type = ContentType.objects.get_for_model(request.journal)
#         request.session = requests.Session() # This isn't right somehow
#         response = views.export_articles_all(request)

        self.client.force_login(self.test_user)
        response = self.client.get( "/plugins/imports/articles/all/", SERVER_NAME='testserver',)
        self.assertEqual(response.status_code, 200)
