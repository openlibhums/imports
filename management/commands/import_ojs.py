import getpass
from journal import models

from django.core.management.base import BaseCommand
from plugins.imports import ojs


class Command(BaseCommand):
    """ Imports back content from target OJS Journal"""

    help = "Imports issues and articles from the target OJS journal"

    def add_arguments(self, parser):
        parser.add_argument('ojs_journal_url')
        parser.add_argument('ojs_username')
        parser.add_argument('journal_code')
        parser.add_argument('--ojs_password', default=None)
        parser.add_argument('--dry-run', action="store_true", default=False)

    def handle(self, *args, **options):
        journal = models.Journal.objects.get(code=options["journal_code"])
        if not options["ojs_password"]:
            password = getpass.getpass(
                "Enter password for user %s: " % options["ojs_username"])
        client = ojs.OJSJanewayClient(
            options["ojs_journal_url"],
            options["ojs_username"],
            options["ojs_password"] or password,
        )

        ojs.import_articles(client, journal)
