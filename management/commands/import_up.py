import getpass
from journal import models

from django.core.management.base import BaseCommand
from plugins.imports import ojs


class Command(BaseCommand):
    """ Imports back content from target UP Journal"""

    help = "Imports issues and articles from the target UP journal"

    def add_arguments(self, parser):
        parser.add_argument('journal_url')
        parser.add_argument('username')
        parser.add_argument('journal_code')
        parser.add_argument('--password', default=None)
        parser.add_argument('--dry-run', action="store_true", default=False)
        parser.add_argument('--editorial', action="store_true", default=False,
                            help="Imports only content in the editorial flow")

    def handle(self, *args, **options):
        journal = models.Journal.objects.get(code=options["journal_code"])
        if not options["password"]:
            password = getpass.getpass(
                "Enter password for user %s: " % options["username"])
        client = ojs.clients.UPJanewayClient(
            options["journal_url"],
            options["username"],
            options["password"] or password,
        )

        ojs.import_users(client, journal)
        if options["editorial"]:
            ojs.import_unassigned_articles(client, journal)
            ojs.import_in_review_articles(client, journal)
            ojs.import_in_editing_articles(client, journal)
        else:
            ojs.import_published_articles(client, journal)
            ojs.import_issues(client, journal)
