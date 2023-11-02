import json
import os
import pathlib

from journal import models
from core.models import Account
from django.core.management.base import BaseCommand

from plugins.imports.mediacommons import import_article


class Command(BaseCommand):
    """ Imports an article from its mediacommos JSON metadata file"""

    help = "Imports an article form the metadata of a mediacommons JSON file"

    def add_arguments(self, parser):
        parser.add_argument(
            'path',
            help="A path to a JSON document or a directory"
                " containing JSON documents"
        )
        parser.add_argument('-j', '--journal_code')
        parser.add_argument('-o', '--owner_id', default=1)

    def handle(self, *args, **options):
        journal = models.Journal.objects.get(code=options["journal_code"])
        owner = Account.objects.get(pk=options["owner_id"])
        if os.path.isdir(options["path"]):
            filenames = [
                pathlib.Path(root, filename)
                for root, _, filenames in os.walk(options["path"])
                for filename in filenames
            ]
        else:
            filenames = [options["path"]]
        for filename in filenames:
            with open(filename, "r") as json_file:
                data = json.loads(json_file.read())
                article = import_article( journal, owner, data)
