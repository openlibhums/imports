"""
Test cases for export in imports plugin

Run with
python manage.py test imports.tests.test_export

Debug with
from nose.tools import set_trace; set_trace()

"""

from django.test import TestCase

from plugins.imports import utils, export, views
from submission import models as submission_models
from journal import models as journal_models
from utils.testing import helpers

from rest_framework import routers
from django.http import HttpRequest
import csv

from plugins.imports.tests.test_utils import CSV_DATA_1, run_import


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
        router = routers.DefaultRouter()
        router.register(r'exportfiles', views.ExportFilesViewSet, basename='exportfile')
        article_1 = submission_models.Article.objects.get(id=1)
        article_1.export_files = article_1.exportfile_set.all()
        filepath, csv_name = export.export_using_import_format([article_1])
        with open(filepath,'r') as export_csv:
            csv_string = export_csv.read()

        expected_csv_string = "Article title,Article filename,Article abstract," \
            "Article section,Keywords,License,Language,Author Salutation,Author surname," \
            "Author given name,Author middle name,Author email," \
            "Author institution,Author is primary (Y/N),Author ORCID," \
            "Author department,Author biography,Author is corporate (Y/N)," \
            "Article ID,DOI,DOI (URL form),Article sequence,Journal Code,Journal title,ISSN," \
            "Volume number,Issue number,Issue name,Issue pub date,Stage\n" \
            'Variopleistocene Inquilibriums,,How it all went down.,Article,"dinosaurs,Socratic teaching",' \
            "CC BY-NC-SA 4.0,English,Prof,Person3,Unreal,J.,unrealperson3@example.com," \
            "University of Michigan Medical School,Y,,Cancer Center,Prof Unreal J. Person3 " \
            "teaches dinosaurs but they are employed in a hospital.,N,1,,,,TST,Journal One,0000-0000," \
            "1,1,Fall 2021,2021-09-15 13:58:59+0000,Editor Copyediting\n" \
            ",,,,,,,,Person5,Unreal,J.,unrealperson5@example.com,University of Calgary," \
            "N,,Anthropology,Unreal J. Person5 is the author of <i>Being</i>.,N\n" \
            ",,,,,,,,Person6,Unreal,J.,unrealperson6@example.com,University of Mars," \
            "N,,Crater Nine,Does Unreal J. Person6 exist?,N\n" \

        self.assertEqual(csv_string, expected_csv_string)

    def test_sorted_export_headers_match_import_headers(self):
        router = routers.DefaultRouter()
        router.register(r'exportfiles', views.ExportFilesViewSet, basename='exportfile')
        article_1 = submission_models.Article.objects.get(id=1)
        article_1.export_files = article_1.exportfile_set.all()
        filepath, csv_name = export.export_using_import_format([article_1])
        with open(filepath,'r') as export_csv:
            sorted_exported_headers = ','.join(sorted(export_csv.readlines()[0][:-1].split(',')))

        # remove this header that's in the export but not in the import
        # see https://github.com/BirkbeckCTP/imports/issues/38
        sorted_exported_headers = sorted_exported_headers.replace(
            'Article sequence,',
            ''
        )

        # add in headers that need to be added to export
        # see https://github.com/BirkbeckCTP/imports/issues/39
        sorted_exported_headers = sorted_exported_headers.replace(
            'DOI (URL form),ISSN',
            'DOI (URL form),Date accepted,Date published,ISSN'
        )

        sorted_expected_headers = ','.join(sorted(CSV_DATA_1.splitlines()[0].split(',')))
        self.assertEqual(sorted_exported_headers, sorted_expected_headers)
