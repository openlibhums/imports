import pprint

from django.core.management.base import BaseCommand
from journal import models
from core.models import Account

from plugins.imports.jats import import_jats_zipped


class Command(BaseCommand):
    """ Imports zipped articles in JATS XML format file"""

    help = "Imports zipped articles in JATS XML Format"

    def add_arguments(self, parser):
        parser.add_argument('zip_file')
        parser.add_argument('--journal_code')
        parser.add_argument('--owner_id', default=1)
        parser.add_argument('--dry-run', action="store_true", default=False)

    def handle(self, *args, **options):
        journal = None
        if options["journal_code"]
            journal = models.Journal.objects.get(code=options["journal_code"])
        owner = Account.objects.get(pk=options["owner_id"])
        persist = True
        if options["dry_run"]:
            persist = False
        articles = import_jats_zipped(
            options["zip_file"], journal,
            owner=owner, persist=persist,
        )
        for article in articles:
            if not persist:
                pprint.pprint(article)
            else:
                print("Imported Article %s" % article)
