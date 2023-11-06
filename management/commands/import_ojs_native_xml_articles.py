from django.core.management.base import BaseCommand

from plugins.imports.ojs import native

from journal import models as journal_models
from core import models as core_models


class Command(BaseCommand):
    """ Imports back content from OJS Native XML"""
    help = "Imports journals from the OJS Native XML"

    def add_arguments(self, parser):
        parser.add_argument('xml_path')
        parser.add_argument('journal_code', default=None)
        parser.add_argument('owner_id', default=None)
        parser.add_argument('stage', default=None)

    def handle(self, *args, **options):
        with open(options.get('xml_path'), 'rb') as issue_file:

            xml_content = issue_file.read()
            journal = journal_models.Journal.objects.get(
                code=options.get('journal_code')
            )
            owner = core_models.Account.objects.get(
                pk=options.get('owner_id')
            )
            stage = options.get('stage')
            articles_imported, articles_updated = native.import_issues(
                xml_content,
                journal,
                owner,
                stage,
            )
            print(f'Imported: {len(articles_imported)}, updated: {len(articles_updated)}')