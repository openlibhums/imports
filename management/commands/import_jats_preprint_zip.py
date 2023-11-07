import pprint

from django.core.management.base import BaseCommand
from repository import models
from core.models import Account

from plugins.imports.jats import import_jats_preprint_zipped


class Command(BaseCommand):
    """ Imports zipped articles in JATS XML format file"""

    help = "Imports zipped articles in JATS XML Format"

    def add_arguments(self, parser):
        parser.add_argument('zip_file')
        parser.add_argument('-r', '--repository_code')
        parser.add_argument('-o', '--owner_id', default=1)
        parser.add_argument('-d', '--dry-run', action="store_true", default=False)

    def handle(self, *args, **options):
        repository = None
        if options["repository_code"]:
            repository = models.Repository.objects.get(
                short_name=options["repository_code"]
            )
        owner = Account.objects.get(pk=options["owner_id"])
        persist = True
        if options["dry_run"]:
            persist = False
        preprints = import_jats_preprint_zipped(
            options["zip_file"],
            repository,
            owner=owner,
            persist=persist,
        )
        for preprint in preprints:
            if not persist:
                pprint.pprint(preprint)
            else:
                print("Imported Preprint %s" % preprint)
