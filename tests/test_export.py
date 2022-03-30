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
        run_import(csv_data_2, owner=cls.test_user)
        router = routers.DefaultRouter()
        router.register(r'exportfiles', views.ExportFilesViewSet, basename='exportfile')

    def test_export_using_import_format(self):
        self.maxDiff = None
        article_1 = submission_models.Article.objects.get(id=1)
        article_1.export_files = article_1.exportfile_set.all()
        filepath, _csv_name = export.export_using_import_format([article_1])
        with open(filepath,'r') as export_csv:
            csv_dict = dict_from_csv_string(export_csv.read())

        expected_csv_data = dict_from_csv_string(CSV_DATA_1)

        # account for Janeway-assigned article ID (also placed as File import identifier)
        expected_csv_data[1]['Janeway ID'] = '1'
        expected_csv_data[1]['File import identifier'] = '1'

        self.assertEqual(expected_csv_data, csv_dict)

    def test_sorted_export_headers_match_import_headers(self):
        article_1 = submission_models.Article.objects.get(id=1)
        article_1.export_files = article_1.exportfile_set.all()
        filepath, csv_name = export.export_using_import_format([article_1])
        with open(filepath,'r') as export_csv:
            sorted_exported_headers = ','.join(sorted(export_csv.readlines()[0][:-1].split(',')))

        sorted_expected_headers = ','.join(sorted(CSV_DATA_1.splitlines()[0].split(',')))
        self.assertEqual(sorted_exported_headers, sorted_expected_headers)

    def test_export_article_with_no_frozen_authors(self):
        self.maxDiff = None
        csv_data_3 = dict_from_csv_string(CSV_DATA_1)
        run_import(csv_data_3, owner=self.test_user)
        imported_article = submission_models.Article.objects.last()
        for frozen_author in imported_article.frozen_authors():
            frozen_author.article = None
            frozen_author.author = None
            frozen_author.save()
        imported_article.export_files = imported_article.exportfile_set.all()
        filepath, csv_name = export.export_using_import_format([imported_article])
        with open(filepath,'r') as export_csv:
            csv_dict = dict_from_csv_string(export_csv.read())

        # account for Janeway-assigned article ID (also placed as File import identifier)
        expected_csv_data = csv_data_3
        expected_csv_data[1]['Janeway ID'] = str(imported_article.pk)
        expected_csv_data[1]['File import identifier'] = str(imported_article.pk)

        # As account data will be pulled for authors, there won't be a name suffix
        expected_csv_data[1]['Author suffix'] = ''

        self.assertEqual(expected_csv_data, csv_dict)

    def test_export_article_with_frozen_authors_but_no_accounts(self):
        self.maxDiff = None
        csv_data_3 = dict_from_csv_string(CSV_DATA_1)
        run_import(csv_data_3, owner=self.test_user)
        imported_article = submission_models.Article.objects.last()
        for frozen_author in imported_article.frozen_authors():
            frozen_author.author = None
            frozen_author.save()
        imported_article.export_files = imported_article.exportfile_set.all()
        filepath, csv_name = export.export_using_import_format([imported_article])
        with open(filepath,'r') as export_csv:
            csv_dict = dict_from_csv_string(export_csv.read())

        # account for Janeway-assigned article ID (also placed as File import identifier)
        expected_csv_data = csv_data_3
        expected_csv_data[1]['Janeway ID'] = str(imported_article.pk)
        expected_csv_data[1]['File import identifier'] = str(imported_article.pk)

        # As account data will not be accessible, there won't be a name suffix
        expected_csv_data[1]['Author suffix'] = ''

        # As account data will not be accessible, there won't be a salutation
        expected_csv_data[1]['Author salutation'] = ''

        # As account data will not be accessible, non-primary author will be assumed
        expected_csv_data[1]['Author is primary (Y/N)'] = 'N'

        self.assertEqual(expected_csv_data, csv_dict)
