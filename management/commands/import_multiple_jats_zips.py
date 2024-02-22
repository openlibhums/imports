import os
import mimetypes

from django.core.management.base import BaseCommand
from django.core.management import call_command

from utils.logger import get_logger
from journal import models as jm
from core import models as cm
from plugins.imports import jats, models
from cron.models import Request
from press import models as pm


logger = get_logger(__name__)


class Command(BaseCommand):
    """ Imports zipped articles in JATS XML format file"""

    help = "Imports zipped articles in JATS XML Format"

    def add_arguments(self, parser):
        parser.add_argument('folder_path')
        parser.add_argument('-j', '--journal_code')
        parser.add_argument('-o', '--owner_id', default=1)
        parser.add_argument('-d', '--dry-run', action="store_true", default=False)

    def handle(self, *args, **options):
        successes = []
        all_errors = []
        folder_path = options.get('folder_path')
        journal = None
        if options["journal_code"]:
            journal = jm.Journal.objects.get(code=options["journal_code"])
        owner = cm.Account.objects.get(pk=options["owner_id"])
        persist = False if options.get('dry_run') else True

        if os.path.exists(
            folder_path,
        ):
            zip_files = []
            for root, dirs, filenames in os.walk(folder_path):
                for filename in filenames:
                    mimetype, _ = mimetypes.guess_type(filename)
                    if mimetype == 'application/zip':
                        zip_files.append(os.path.join(root, filename))

            if zip_files:
                for zip_file in zip_files:
                    articles, errors = jats.import_jats_zipped(
                        zip_file,
                        journal,
                        owner=owner,
                        persist=persist,
                    )

                    for article in articles:
                        successes.append(
                            f'Imported {article}',
                        )
                        call_command('register_crossref_doi', article[1].pk)
                    for error in errors:
                        all_errors.append(
                            {
                                'zip_file': os.path.basename(zip_file),
                                'error': error[1],
                            }
                        )

            if zip_files:
                to_notify = models.AutomatedImportNotification.objects.all()
                request = Request()
                press = pm.Press.objects.first()
                request.press = press
                request.site_type = press

                for n in to_notify:
                    n.send_notification(
                        [os.path.basename(z) for z in zip_files],
                        all_errors,
                        request,
                    )

