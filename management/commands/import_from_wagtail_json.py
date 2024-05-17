import os
from django.core.management.base import BaseCommand
from press.models import Press

from plugins.imports.import_wagtail import import_from_json


class Command(BaseCommand):
    """ Imports Wagtail pages from source JSON dump"""

    help = (
            "Imports Wagtail pages from source json dump."
            "You can export your pages in JSON with `wagtail-import-export`"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'path',
            help="A path to a JSON document or a directory"
                " containing JSON documents"
        )
        parser.add_argument(
                '--site-prefix', "-p",
                default=None,
                help="The site prefix to strip out, used by wagtail pages"
        )
        parser.add_argument('--dry-run', default=False, action="store_true")

    def handle(self, *args, **options):
        press = Press.objects.first()
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
                json_data = json_file.read()
                import_from_json(press, json_data, site_prefix=options["site_prefix"])
