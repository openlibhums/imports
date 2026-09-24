from django.test import TestCase, override_settings

from plugins.imports import utils, export, views, plugin_settings
from submission import models as submission_models
from journal import models as journal_models
from utils.testing import helpers

from rest_framework import routers
from django.conf import settings
from django.http import HttpRequest
from django.urls import clear_url_caches, reverse
import csv
import importlib
import io
import zipfile

from plugins.imports.tests.test_utils import CSV_DATA_1, run_import, dict_from_csv_string


def reload_urlconf():
    """
    Reloads the URLconf so the URLs of plugins installed after the first
    import of core.include_urls become available.
    """
    importlib.reload(importlib.import_module('core.include_urls'))
    importlib.reload(importlib.import_module(settings.ROOT_URLCONF))
    clear_url_caches()


def export_rows(articles):
    """
    Runs the import-format export for the given articles and returns the
    CSV header names and the rows as dicts.
    """
    for article in articles:
        article.export_files = article.exportfile_set.all()
    filepath, _csv_name = export.export_using_import_format(articles)
    with open(filepath, 'r', encoding='utf-8') as export_csv:
        reader = csv.DictReader(export_csv)
        return reader.fieldnames, list(reader)


def rows_from_zip_response(response):
    """
    Reads the article_data.csv file out of a zipped export response.
    """
    content = b''.join(response.streaming_content)
    with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
        csv_text = zip_file.read('article_data.csv').decode('utf-8')
    return list(csv.DictReader(io.StringIO(csv_text)))


class TestExport(TestCase):
    @classmethod
    def setUpTestData(cls):

        journal_one, journal_two = helpers.create_journals()
        issue_type = journal_models.IssueType.objects.get_or_create(
            journal=journal_one,
            code='issue'
        )
        helpers.create_roles(
            'author',
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

    def test_export_article(self):
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

        # As account data will not be accessible, non-primary author will be assumed
        expected_csv_data[1]['Author is primary (Y/N)'] = 'N'

        self.assertEqual(expected_csv_data, csv_dict)

    def test_export_article_with_no_authors(self):
        self.maxDiff = None
        csv_data = dict_from_csv_string(CSV_DATA_1)
        run_import(csv_data, owner=self.test_user)

        # Wipe authors
        imported_article = submission_models.Article.objects.last()
        imported_article.frozenauthor_set.all().delete()

        # Test
        imported_article.export_files = imported_article.exportfile_set.all()
        filepath, csv_name = export.export_using_import_format([imported_article])
        lines = len([l for l in open(filepath,'r')])


        self.assertEqual(2, lines)


@override_settings(URL_CONFIG='domain')
class TestExportDeletedFieldAnswers(TestCase):
    """
    Regression tests for openlibhums/imports#129: FieldAnswer.field is
    SET_NULL, so deleting a custom submission Field leaves answers with no
    field. Exporting those articles raised an AttributeError (a 500).
    """

    @classmethod
    def setUpTestData(cls):
        cls.press = helpers.create_press()
        cls.journal_one, cls.journal_two = helpers.create_journals()
        plugin_settings.install()
        reload_urlconf()
        cls.editor = helpers.create_editor(cls.journal_one)

        cls.live_field = submission_models.Field.objects.create(
            journal=cls.journal_one,
            name='Funding statement',
            kind='text',
            order=1,
            help_text='',
        )
        first_deleted_field = submission_models.Field.objects.create(
            journal=cls.journal_one,
            name='Retired question',
            kind='text',
            order=2,
            help_text='',
        )
        second_deleted_field = submission_models.Field.objects.create(
            journal=cls.journal_one,
            name='Another retired question',
            kind='text',
            order=3,
            help_text='',
        )

        cls.article_with_orphan = helpers.create_article(
            cls.journal_one,
            stage=submission_models.STAGE_PUBLISHED,
        )
        submission_models.FieldAnswer.objects.create(
            field=cls.live_field,
            article=cls.article_with_orphan,
            answer='Funded by the Example Trust',
        )
        submission_models.FieldAnswer.objects.create(
            field=first_deleted_field,
            article=cls.article_with_orphan,
            answer='Orphaned answer',
        )

        cls.article_with_two_orphans = helpers.create_article(
            cls.journal_one,
            stage=submission_models.STAGE_PUBLISHED,
        )
        submission_models.FieldAnswer.objects.create(
            field=first_deleted_field,
            article=cls.article_with_two_orphans,
            answer='First orphaned answer',
        )
        submission_models.FieldAnswer.objects.create(
            field=second_deleted_field,
            article=cls.article_with_two_orphans,
            answer='Second orphaned answer',
        )

        cls.article_without_orphans = helpers.create_article(
            cls.journal_one,
            stage=submission_models.STAGE_PUBLISHED,
        )
        submission_models.FieldAnswer.objects.create(
            field=cls.live_field,
            article=cls.article_without_orphans,
            answer='Self-funded',
        )

        first_deleted_field.delete()
        second_deleted_field.delete()

    def setUp(self):
        self.client.force_login(self.editor)

    def test_live_answer_exported_under_field_name(self):
        _headers, rows = export_rows([self.article_with_orphan])
        self.assertEqual(
            rows[0]['Funding statement'],
            'Funded by the Example Trust',
        )

    def test_orphaned_answer_exported_under_unknown_field(self):
        headers, rows = export_rows([self.article_with_orphan])
        self.assertIn('Unknown Field', headers)
        self.assertNotIn('Unknown Field 2', headers)
        self.assertEqual(rows[0]['Unknown Field'], 'Orphaned answer')

    def test_multiple_orphaned_answers_numbered_in_answer_order(self):
        headers, rows = export_rows([self.article_with_two_orphans])
        self.assertIn('Unknown Field', headers)
        self.assertIn('Unknown Field 2', headers)
        self.assertEqual(rows[0]['Unknown Field'], 'First orphaned answer')
        self.assertEqual(rows[0]['Unknown Field 2'], 'Second orphaned answer')

    def test_no_unknown_field_header_without_orphaned_answers(self):
        headers, rows = export_rows([self.article_without_orphans])
        self.assertFalse(
            [header for header in headers if header.startswith('Unknown Field')]
        )
        self.assertEqual(rows[0]['Funding statement'], 'Self-funded')

    def test_export_all_view_with_orphaned_answers(self):
        response = self.client.post(
            reverse('import_export_articles_all'),
            data={'export_all': ''},
            SERVER_NAME=self.journal_one.domain,
        )
        self.assertEqual(response.status_code, 200)
        rows = rows_from_zip_response(response)
        answers = {row['Janeway ID']: row['Unknown Field'] for row in rows}
        self.assertEqual(
            answers[str(self.article_with_orphan.pk)],
            'Orphaned answer',
        )

    def test_export_filtered_view_with_orphaned_answers(self):
        response = self.client.post(
            '{}?stage={}'.format(
                reverse('import_export_articles_all'),
                submission_models.STAGE_PUBLISHED,
            ),
            data={'export_all': ''},
            SERVER_NAME=self.journal_one.domain,
        )
        self.assertEqual(response.status_code, 200)
        rows = rows_from_zip_response(response)
        self.assertEqual(len(rows), 3)

    def test_single_article_export_view_with_orphaned_answers(self):
        response = self.client.post(
            reverse('import_export_articles_all'),
            data={
                'export_all': '',
                'article_id': self.article_with_two_orphans.pk,
            },
            SERVER_NAME=self.journal_one.domain,
        )
        self.assertEqual(response.status_code, 200)
        rows = rows_from_zip_response(response)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Unknown Field'], 'First orphaned answer')
        self.assertEqual(rows[0]['Unknown Field 2'], 'Second orphaned answer')
