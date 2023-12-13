import logging
import pprint

from django.core.management.base import BaseCommand
from repository import models
from core.models import Account
from utils.logger import get_logger

from plugins.imports.jats import import_jats_zipped

logger = get_logger(__name__)


class Command(BaseCommand):
    """ Imports zipped preprints in JATS XML format file"""

    help = "Imports zipped preprints in JATS XML Format"

    def add_arguments(self, parser):
        parser.add_argument('zip_file')
        parser.add_argument('--repo_code')
        parser.add_argument('--owner_id', default=1)
        parser.add_argument('--dry-run', action="store_true", default=False)

    def handle(self, *args, **options):
        verbosity = int(options['verbosity'])
        if verbosity > 2:
            logger.setLevel(logging.DEBUG)
        elif verbosity > 1:
            logger.setLevel(logging.INFO)

        repo = None
        if options["repo"]:
            repo = models.Repository.objects.get(
                code=options["journal_code"]
            )
        owner = Account.objects.get(
            pk=options.get("owner_id")
        )
        preprints = import_preprint_jats_zipped(
            options["zip_file"],
            repo,
            owner=owner,
            persist=persist,
        )
