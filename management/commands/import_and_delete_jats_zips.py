import os
import pprint

from django.core.management.base import BaseCommand
from journal import models
from core.models import Account

from zipfile import BadZipfile

from plugins.imports.jats import import_jats_zipped


class Command(BaseCommand):
    """ Imports zipped articles in JATS XML format file"""

    help = "Imports zipped articles in JATS XML Format"

    def add_arguments(self, parser):
        parser.add_argument('folder')
        parser.add_argument('-j', '--journal_code')
        parser.add_argument('-o', '--owner_id', default=1)
        parser.add_argument('-d', '--dry-run', action="store_true", default=False)

    def handle(self, *args, **options):
        journal = None
        if options["journal_code"]:
            journal = models.Journal.objects.get(code=options["journal_code"])
        folder_path = options.get('folder')
        owner = Account.objects.get(pk=options["owner_id"])
        zip_files = [
            os.path.join(folder_path, f) for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))
        ]
        persist = True
        if options["dry_run"]:
            persist = False

        for zip_file in zip_files:
            try:
                articles = import_jats_zipped(
                    zip_file, journal,
                    owner=owner, persist=persist,
                )
                for article in articles:
                    if not persist:
                        pprint.pprint(article)
                    else:
                        print("Imported Article %s" % article)
                if persist:
                    os.unlink(zip_file)
            except BadZipfile as e:
                print(f"Error importing: {e}")
