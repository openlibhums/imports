import requests
from tqdm import tqdm

from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile

from journal import models
from core import models as core_models, files

import logging
logging.getLogger("requests").setLevel(logging.WARNING)


class Command(BaseCommand):
    """Fetches UP article images from their API."""

    def add_arguments(self, parser):
        parser.add_argument('-j', '--journal_code')
        parser.add_argument('-u', '--up_journal_code')
        parser.add_argument('-b', '--base_url')
        parser.add_argument('-o', '--owner')

    def handle(self, *args, **options):
        base_url = options.get('base_url')
        up_journal_code = options.get('up_journal_code')
        owner = core_models.Account.objects.get(pk=options.get('owner'))
        journal = models.Journal.objects.get(
            code=options.get('journal_code'),
        )
        galleys = core_models.Galley.objects.filter(
            article__journal=journal,
        )

        # Loop through all of the galleys and for those with missing
        # images try to get them.
        for galley in tqdm(galleys):
            missing_images = galley.has_missing_image_files()
            if missing_images and galley.article.get_doi():
                article_id = galley.article.get_doi().split('.')[-1]
                up_api_url = f"https://taskmaster.ubiquity.press/api/article/{up_journal_code}/{article_id}/html"
                r = requests.get(up_api_url)
                data = r.json().get('dependent_files')

                if data:
                    for k, v in data.items():
                        if k in missing_images:
                            image_url = f"{base_url}jnl-{up_journal_code}-files/{v}"
                            image = requests.get(image_url)
                            django_file = ContentFile(image.content)
                            django_file.name = k
                            new_file = files.save_file_to_article(
                                django_file,
                                galley.article,
                                owner,
                            )
                            new_file.is_galley = False
                            new_file.label = 'Image File'
                            new_file.original_filename = k
                            new_file.save()
                            galley.images.add(new_file)


