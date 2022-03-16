
import csv
import pprint
import uuid

from core.models import Account
from django.core.management.base import BaseCommand
from journal import models

from plugins.imports.utils import DummyRequest
from plugins.imports.utils import update_article_metadata

class Command(BaseCommand):
    """ CLI interface for the CSV importer"""

    help = "CLI interface for the CSV importer"

    def add_arguments(self, parser):
        parser.add_argument('csv_file')
        parser.add_argument('--owner-id', default=1)

    def handle(self, *args, **options):
        owner = Account.objects.get(pk=options["owner_id"])

        with open(options["csv_file"], "r") as f:
            reader = csv.DictReader(f, delimiter=",")
            rows, actions = update_article_metadata(
                reader,
                owner=owner,
                import_id=uuid.uuid4()
            )

            for row in rows:
                if row.get("error"):
                    self.stderr.write(f"Row failed: {row.error}\n{row.article}")
            for action in actions:
                print(action)


