from django.test import TestCase, RequestFactory, override_settings
from core import urls
from core import models as core_models
from utils.testing import helpers
from utils.install import update_issue_types
from plugins.imports.tests.test_utils import CSV_DATA_1, run_import, dict_from_csv_string
from plugins.imports import views
from submission import models as submission_models
from journal import models as journal_models
from django.http import HttpRequest
from core import logic as core_logic, plugin_installed_apps
from rest_framework import routers
from django.core.urlresolvers import reverse
from django.shortcuts import redirect
from utils import shared as utils_shared
from django.core.management import call_command
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
import requests
from submission import models as submission_models


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

        plugins = plugin_installed_apps.load_plugin_apps(settings.BASE_DIR)
        cls.elements = core_models.BASE_ELEMENTS

    @override_settings(URLCONFIG='domain')
    def test_export_stages(self):
        importable_stages = [
            submission_models.STAGE_UNASSIGNED,
            submission_models.STAGE_EDITOR_COPYEDITING,
            submission_models.STAGE_READY_FOR_PUBLICATION,
            submission_models.STAGE_PUBLISHED,
            *submission_models.Article._meta.get_field("stage").dynamic_choices
        ]

        exportable_stage_choices = [
            element.stage for element in self.journal_one.workflow().elements.all()
        ]

        csv_data = dict_from_csv_string(CSV_DATA_1)
        for stage in importable_stages:
            csv_data[1]['Stage'] = stage
            run_import(csv_data, owner=self.test_user)

        self.client.force_login(self.test_user)
        for stage in exportable_stage_choices:
            response = self.client.get(
                '/plugins/imports/articles/all/',
                SERVER_NAME='testserver',
                data = {'stage':stage},
            )
            self.assertEqual(200, response.status_code)
