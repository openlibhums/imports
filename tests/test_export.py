from django.test import TestCase

from plugins.imports import utils, export, views
from submission import models as submission_models
from journal import models as journal_models
from utils.testing import helpers

from rest_framework import routers
from django.http import HttpRequest
import csv

from plugins.imports.tests.test_utils import CSV_DATA_1, run_import, dict_from_csv_string


class TestExport(TestCase):
    @classmethod
    def setUpTestData(cls):

        journal_one, journal_two = helpers.create_journals()
        issue_type = journal_models.IssueType.objects.get_or_create(
            journal=journal_one,
            code='issue'
        )

        cls.mock_request = HttpRequest()
        cls.test_user = helpers.create_user(username='unrealperson12@example.com')
        cls.mock_request.user = cls.test_user

        csv_data_2 = CSV_DATA_1
        run_import(csv_data_2, cls.mock_request)

    def test_export_using_import_format(self):
        self.maxDiff = None
        router = routers.DefaultRouter()
        router.register(r'exportfiles', views.ExportFilesViewSet, basename='exportfile')
        article_1 = submission_models.Article.objects.get(id=1)
        article_1.export_files = article_1.exportfile_set.all()
        filepath, _csv_name = export.export_using_import_format([article_1])
        with open(filepath,'r') as export_csv:
            csv_dict = dict_from_csv_string(export_csv.read())

        expected_csv_data = dict_from_csv_string(CSV_DATA_1)

        # account for Janeway-assigned article ID (also placed as File import identifier)
        expected_csv_data[1]['Article ID'] = '1'
        expected_csv_data[1]['File import identifier'] = '1'

        self.assertEqual(expected_csv_data, csv_dict)

    def test_sorted_export_headers_match_import_headers(self):
        router = routers.DefaultRouter()
        router.register(r'exportfiles', views.ExportFilesViewSet, basename='exportfile')
        article_1 = submission_models.Article.objects.get(id=1)
        article_1.export_files = article_1.exportfile_set.all()
        filepath, csv_name = export.export_using_import_format([article_1])
        with open(filepath,'r') as export_csv:
            sorted_exported_headers = ','.join(sorted(export_csv.readlines()[0][:-1].split(',')))

        sorted_expected_headers = ','.join(sorted(CSV_DATA_1.splitlines()[0].split(',')))
        self.assertEqual(sorted_exported_headers, sorted_expected_headers)
