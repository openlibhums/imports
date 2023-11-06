from django.core.management.base import BaseCommand

from plugins.imports.ojs import native
from journal import models as journal_models

class Command(BaseCommand):
    """ Imports users from OJS Native XML"""
    help = "Imports users from the OJS Native XML"

    def add_arguments(self, parser):
        parser.add_argument('xml_path')
        parser.add_argument('journal_code')

    def handle(self, *args, **options):
        with open(options.get('xml_path')) as user_file:
            xml_content = user_file.read()
            journal = journal_models.Journal.objects.get(
                code=options.get('journal_code')
            )
            accounts = native.import_users(
                xml_content,
                journal,
            )
            print(f'{len(accounts)} accounts imported.')
