from django.test import TestCase

from plugins.imports import plugin_settings

import csv

def get_headers_at_path(path):
    with open(path, 'r') as the_csv:
        return set(the_csv.readlines()[0][:-1].split(','))

class TestDocs(TestCase):
    """
    Tests to check that the templates and samples provided in docs are correct
    """

    def test_template_headers(self):
        settings_headers = set(plugin_settings.UPDATE_CSV_HEADERS)
        template_headers = get_headers_at_path(
            'plugins/imports/docs/source/_static/metadata_template.csv')
        self.assertEqual(settings_headers, template_headers)

    def test_sample_import_headers(self):
        settings_headers = set(plugin_settings.UPDATE_CSV_HEADERS)
        sample_import_headers = get_headers_at_path(
            'plugins/imports/docs/source/_static/sample_import.csv')
        self.assertEqual(settings_headers, sample_import_headers)

    def test_sample_update_headers(self):
        settings_headers = set(plugin_settings.UPDATE_CSV_HEADERS)
        sample_update_headers = get_headers_at_path(
            'plugins/imports/docs/source/_static/sample_update.csv')
        self.assertEqual(settings_headers, sample_update_headers)
