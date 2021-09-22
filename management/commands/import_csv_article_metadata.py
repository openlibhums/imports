
import csv
import pprint

from core.models import Account
from django.core.management.base import BaseCommand
from journal import models

from plugins.imports.utils import DummyRequest
from plugins.imports.utils import import_article_metadata

class Command(BaseCommand):
    """ CLI interface for the CSV importer"""

    help = "CLI interface for the CSV importer"

    def add_arguments(self, parser):
        parser.add_argument('csv_file')
        parser.add_argument('journal_code')
        parser.add_argument('--owner-id', default=1)

    def handle(self, *args, **options):
        journal = models.Journal.objects.get(code=options["journal_code"])
        owner = Account.objects.get(pk=options["owner_id"])

        with open(options["csv_file"], "r") as f:
            reader = csv.reader(f, delimiter=",")
            request = DummyRequest(owner, journal)
            _, err, err_file= import_article_metadata(request, reader)

            for e in err:
                print(e)
            print("Error file: %s" % err_file)


