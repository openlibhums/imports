import getpass

from django.core.management.base import BaseCommand, CommandError

from journal import models as journal_models
from core import models as core_models
from plugins.imports import ojs
from plugins.imports.ojs.ojs3_importers import delocalise


class Command(BaseCommand):
    """ Imports back content from target OJS Journal"""
    IMPORT_CLIENT = ojs.clients.OJS3APIClient

    help = "Imports journals from the target OJS journal"

    def add_arguments(self, parser):
        parser.add_argument('ojs_url')
        parser.add_argument('username')
        parser.add_argument('--password', default=None)
        parser.add_argument('--journal_code', required=True, default=None)
        parser.add_argument('--posted_by', required=True, default=None)
        parser.add_argument("--dry_run", action="store_true", default=False)


    def handle(self, *args, **options):
        password = options.get('password')
        journal_code = options.get('journal_code')
        dry_run = options.get('dry_run')
        posted_by = options.get('posted_by')

        if not password:
            password = getpass.getpass(
                "Enter password for user %s: " % options["username"]
            )

        client = self.IMPORT_CLIENT(
            options["ojs_url"],
            options["username"],
            options["password"] or password,
            )
        try:
            journal = journal_models.Journal.objects.get(
                code=journal_code,
            )
        except journal_models.Journal.DoesNotExist:
            raise CommandError(
                f"[X] Journal with code '{journal_code}' does not exist.",
            )
        try:
            posted_by = core_models.Account.objects.get(
                pk=posted_by,
            )
        except core_models.Account:
            raise CommandError(
                f"[X] User with ID '{posted_by}' does not exist.",
            )
        announcements = ojs.import_ojs3_announcements(
            client,
            journal,
            posted_by,
            dry_run,
        )

        if dry_run:
            # This is a generator
            count = 0
            for ann in announcements:
                title = delocalise(
                    ann.get("title"),
                )
                self.stdout.write(f"- {title}")
                count += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ Found {count} announcement{'s' if count != 1 else ''}.",
                ),
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ Created {len(announcements)} announcement{'s' if len(announcements) != 1 else ''}.",
                )
            )
