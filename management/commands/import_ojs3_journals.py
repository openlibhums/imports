import getpass
from journal import models

from django.core.management.base import BaseCommand
from plugins.imports import ojs


class Command(BaseCommand):
    """ Imports back content from target OJS Journal"""
    IMPORT_CLIENT = ojs.clients.OJS3APIClient

    help = "Imports journals from the target OJS journal"

    def add_arguments(self, parser):
        parser.add_argument('ojs_url')
        parser.add_argument('username')
        parser.add_argument('--password', default=None)


    def handle(self, *args, **options):
        if not options["password"]:
            password = getpass.getpass(
                "Enter password for user %s: " % options["username"])
        client = self.IMPORT_CLIENT(
            options["ojs_url"],
            options["username"],
            options["password"] or password,
        )
        ojs.import_ojs3_journals(client)
