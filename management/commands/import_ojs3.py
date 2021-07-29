
import getpass
from journal import models

from django.core.management.base import BaseCommand
from plugins.imports import ojs


class Command(BaseCommand):
    """ Imports back content from target OJS Journal"""
    IMPORT_CLIENT = ojs.clients.OJS3APIClient

    help = "Imports issues and articles from the target OJS journal"

    def add_arguments(self, parser):
        parser.add_argument('journal_url')
        parser.add_argument('username')
        parser.add_argument('journal_code')
        parser.add_argument('--password', default=None)
        parser.add_argument('--dry-run', action="store_true", default=False)
        parser.add_argument('--issues', action="store_true", default=False,
                            help="Imports only issues")
        parser.add_argument('--users', action="store_true", default=False,
                            help="Imports only users")
        parser.add_argument('--ojs_id', default=False,
                            help="Imports only the article matching by ojs id")


    def handle(self, *args, **options):
        journal = models.Journal.objects.get(code=options["journal_code"])
        if not options["password"]:
            password = getpass.getpass(
                "Enter password for user %s: " % options["username"])
        client = self.IMPORT_CLIENT(
            options["journal_url"],
            options["username"],
            options["password"] or password,
        )
        if options["issues"]:
            ojs.import_ojs3_issues(client, journal)
        elif options["users"]:
            ojs.import_ojs3_users(client, journal)
        else:
            ojs.import_ojs3_articles(client, journal)
