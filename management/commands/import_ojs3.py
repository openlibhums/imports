
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
        parser.add_argument('--issues', action="store_true", default=False,
                            help="Imports only issues")
        parser.add_argument('--unpublished-issues', action="store_true", default=False,
                            help="Imports only future issues")
        parser.add_argument('--just-galleys', action="store_true", default=False,
                            help="Imports only galleys (articles must exist)")
        parser.add_argument('--issue-id', default=None,
                            help="Imports only the issue matching by ojs id")
        parser.add_argument('--users', action="store_true", default=False,
                            help="Imports only users")
        parser.add_argument('--metrics', action="store_true", default=False,
                            help="Imports Article Metrics")
        parser.add_argument('--ojs_id', default=None,
                            help="Imports only the article matching by ojs id")
        parser.add_argument('--editorial', action="store_true", default=False,
                            help="Include editorial data such as peer reviews")
        parser.add_argument('--ignore-galleys', action="store_true",
                            default=False,
                            help="Do not import article galleys")


    def handle(self, *args, **options):
        journal = models.Journal.objects.get(code=options["journal_code"])
        password = options["password"]
        if not password:
            password = getpass.getpass(
                "Enter password for user %s: " % options["username"])
        client = self.IMPORT_CLIENT(
            options["journal_url"],
            options["username"],
            password,
        )
        if options["issues"]:
            ojs.import_ojs3_issues(client, journal)
        elif options["metrics"]:
            ojs.import_ojs3_metrics(client, journal)
        elif options["issue_id"]:
            ojs.import_ojs3_issues(client, journal, issue_id=options["issue_id"])
        elif options["unpublished_issues"]:
            ojs.import_ojs3_unpublished_issues(client, journal)
        elif options["users"]:
            ojs.import_ojs3_users(client, journal)
        elif options["just_galleys"]:
            ojs.import_ojs3_galleys(client, journal)
        else:
            ojs.import_ojs3_articles(
                client, journal,
                ojs_id=options["ojs_id"],
                editorial=options["editorial"],
                galleys=not options["ignore_galleys"],
            )
