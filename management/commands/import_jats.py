import pprint

from django.core.management.base import BaseCommand
from journal import models
from core.models import Account

from imports.jats import import_jats_article


class Command(BaseCommand):
    """ Imports an article from its JATS XML metadata file"""

    help = "Imports an article form the metadata of a JATS XML galley"

    def add_arguments(self, parser):
        parser.add_argument('jats_xml_path')
        parser.add_argument('journal_code')
        parser.add_argument('--owner_id', default=1)
        parser.add_argument('--dry-run', action="store_true", default=False)

    def handle(self, *args, **options):
        journal = models.Journal.objects.get(code=options["journal_code"])
        owner = Account.objects.get(pk=options["owner_id"])
        with open(options["jats_xml_path"], "r") as jats_file:
            persist = True
            if options["dry_run"]:
                persist = False
            article = import_jats_article(
                jats_file.read(), journal,
                persist=persist,
                filename=jats_file.name,
                owner=owner,
            )
            if not persist:
                pprint.pprint(article)
