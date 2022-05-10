import getpass
from journal import models

from django.core.management.base import BaseCommand
from plugins.imports import ojs


class Command(BaseCommand):
    """ Imports back content from target OJS Journal"""
    IMPORT_CLIENT = ojs.clients.OJSJanewayClient

    help = "Imports issues and articles from the target OJS journal"

    def add_arguments(self, parser):
        parser.add_argument('journal_url')
        parser.add_argument('username')
        parser.add_argument('journal_code')
        parser.add_argument('--password', default=None)
        parser.add_argument('--dry-run', action="store_true", default=False)
        parser.add_argument('--editorial', action="store_true", default=False,
                            help="Imports only content in the editorial flow")
        parser.add_argument('--users', action="store_true", default=False,
                            help="Imports only users")
        parser.add_argument('--sections', action="store_true", default=False,
                            help="Imports only sections")
        parser.add_argument('--collections', action="store_true", default=False,
                            help="Imports only collections")
        parser.add_argument('--issues', action="store_true", default=False,
                            help="Imports only isssues")
        parser.add_argument('--ojs_id', default=False,
                            help="Imports only the article matching by ojs id")
        parser.add_argument('--metrics', action="store_true", default=False,
                            help="Imports only article metrics")
        parser.add_argument('--ignore-galleys', action="store_true",
                            default=False,
                            help="Imports only article metrics")

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

        if options["users"]:
            ojs.import_users(client, journal)

        elif options["editorial"]:
            ojs.import_unassigned_articles(client, journal)
            ojs.import_in_review_articles(client, journal)
            ojs.import_in_editing_articles(client, journal)
        elif options["sections"]:
            ojs.import_sections(client, journal)
        elif options["collections"]:
            ojs.import_collections(client, journal)
        elif options["issues"]:
            ojs.import_issues(client, journal)
        elif options["ojs_id"]:
            ojs.import_article(client, journal, options["ojs_id"])
        elif options["metrics"]:
            ojs.import_metrics(client, journal)
        else:
            ojs.import_published_articles(
                client, journal, not options["ignore_galleys"])
