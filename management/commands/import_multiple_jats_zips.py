import os
import mimetypes

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.contrib.contenttypes.models import ContentType

from utils.logger import get_logger
from journal import models as jm, logic
from core import models as cm
from plugins.imports import jats, models
from cron.models import Request
from press import models as pm
from utils import setting_handler, render_template
from utils.transactional_emails import send_author_publication_notification


logger = get_logger(__name__)


class Command(BaseCommand):
    """ Imports zipped articles in JATS XML format file"""

    help = "Imports zipped articles in JATS XML Format"

    def add_arguments(self, parser):
        parser.add_argument('folder_path')
        parser.add_argument('-j', '--journal_code')
        parser.add_argument('-o', '--owner_id', default=1)
        parser.add_argument('-d', '--dry-run', action="store_true", default=False)
        parser.add_argument('-c', '--crossref-deposit', action="store_true",
                            default=False)
        parser.add_argument('-ch', '--crossref-how-to-cite', action="store_true",
                            default=False)
        parser.add_argument('-n', '--notify-author', action="store_true",
                            default=False)
        parser.add_argument('-m', '--crossref-mailto', type=str)

    def handle(self, *args, **options):
        successes = []
        all_errors = []
        articles = []
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
                        if options.get('crossref_deposit'):
                            call_command(
                                'register_crossref_doi',
                                article[1].pk
                            )
                        if options.get('crossref_how_to_cite'):
                            citation_format = models.CitationFormat.objects.filter(
                                journal=article[1].journal,
                            ).first()
                            if citation_format:
                                call_command(
                                    'fetch_crossref_how_to_cite',
                                    journal=article[1].journal.code,
                                    article_id=article[1].pk,
                                    style=citation_format.format,
                                    locale='en_GB',
                                    mailto='a.byers@bbk.ac.uk',
                                )
                    for error in errors:
                        all_errors.append(
                            {
                                'zip_file': os.path.basename(zip_file),
                                'error': error[1],
                            }
                        )

            if zip_files and persist:
                to_notify = models.AutomatedImportNotification.objects.all()
                request = Request()
                press = pm.Press.objects.first()
                request.press = press
                request.site_type = press
                request.repository = None
                request.POST = {}

                for n in to_notify:
                    n.send_notification(
                        [os.path.basename(z) for z in zip_files],
                        all_errors,
                        request,
                    )

                if options.get('notify_author'):
                    for article_set in articles:
                        article = article_set[1]
                        if article.correspondence_author:
                            request.user = owner
                            request.journal = article.journal
                            request.site_type = article.journal
                            request.model_content_type = ContentType.objects.get_for_model(
                                article.journal,
                            )

                            template = setting_handler.get_setting(
                                'email',
                                'author_publication',
                                request.journal,
                            ).value.replace(
                                " at {{ article.date_published|date:'H:i' }}",
                                "",
                            )
                            message = render_template.get_message_content(
                                request,
                                {'article': article},
                                template,
                                template_is_setting=True,
                            )
                            request.POST = {
                                'notify_author_email': message
                            }
                            send_author_publication_notification(
                                **{
                                    'request': request,
                                    'article': article,
                                    'user_message': message,
                                    'section_editors': False,
                                    'peer_reviewers': False,
                                }
                            )
