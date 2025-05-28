import os

from django.core.management.base import BaseCommand
from plugins.imports.ojs import native

from journal import models as journal_models
from core import models as core_models


class Command(BaseCommand):
    """Imports back content from OJS 3 Native XML"""
    help = "Imports journals from the OJS 3 Native XML"

    def add_arguments(self, parser):
        parser.add_argument(
            'path',
            help="Path to an XML file or a directory containing journal_code subfolders "
                 "with XML files",
        )
        parser.add_argument(
            'owner_id',
        )
        parser.add_argument(
            'stage',
        )

    def handle(
        self,
        *args,
        **options,
    ):
        path = options.get('path')
        owner_id = options.get('owner_id')
        stage = options.get('stage')

        owner = core_models.Account.objects.get(pk=owner_id)

        if os.path.isdir(path):
            for journal_code in os.listdir(path):
                journal_dir = os.path.join(path, journal_code)
                if not os.path.isdir(journal_dir):
                    continue

                try:
                    journal = journal_models.Journal.objects.get(code=journal_code)
                except journal_models.Journal.DoesNotExist:
                    self.stdout.write(
                        self.style.ERROR(
                            f'Journal with code "{journal_code}" not found.',
                        ),
                    )
                    continue

                for xml_filename in os.listdir(journal_dir):
                    if not xml_filename.lower().endswith('.xml'):
                        continue

                    xml_path = os.path.join(journal_dir, xml_filename)
                    self._import_xml(xml_path, journal, owner, stage)

        elif os.path.isfile(path) and path.lower().endswith('.xml'):
            journal_code = input("Enter the journal code for this XML file: ").strip()

            try:
                journal = journal_models.Journal.objects.get(code=journal_code)
            except journal_models.Journal.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(
                        f'Journal with code "{journal_code}" not found.',
                    ),
                )
                return

            self._import_xml(path, journal, owner, stage)
        else:
            self.stdout.write(
                self.style.ERROR(
                    "Invalid path provided. Must be a directory or an XML file.",
                ),
            )

    def _import_xml(
        self,
        xml_path,
        journal,
        owner,
        stage,
    ):
        self.stdout.write(f"Processing: {xml_path}")

        with open(xml_path, 'rb') as xml_file:
            xml_content = xml_file.read()

        articles_imported, articles_updated = native.import_issues(
            xml_content,
            journal,
            owner,
            stage,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f'Imported: {len(articles_imported)}, Updated: {len(articles_updated)} for {xml_path}'
            )
        )
