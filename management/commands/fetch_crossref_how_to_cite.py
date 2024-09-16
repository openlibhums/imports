from django.core.management.base import BaseCommand

import requests
import time
from pprint import pprint

from submission import models


class Command(BaseCommand):
    """For a give journal query crossref for the given citation format
    and update the custom how to cite field."""

    help = "Gets custom how to cite using Crossref."

    def add_arguments(self, parser):
        parser.add_argument('--journal', type=str)
        parser.add_argument('--article_id', type=str)
        parser.add_argument('--style', type=str)
        parser.add_argument('--locale', type=str)
        parser.add_argument('--mailto', type=str)

    def handle(self, *args, **options):
        errors = []
        articles = models.Article.objects.filter(journal__code=options.get('journal'))

        article_id = options.get('article_id')
        if article_id:
            articles = articles.filter(pk=article_id)

        for index, article in enumerate(articles):
            print(f"Getting how to cite for article #{article.pk}. {index}/{articles.count()}")
            if article.get_doi():
                try:
                    r = requests.get(
                        headers={
                            'Accept': 'text/bibliography',
                            'style': options.get('style'),
                            'locale': options.get('locale')
                        },
                        url=f"https://api.crossref.org/v1/works/{article.get_doi()}/transform?mailto={options.get('mailto')}",
                    )
                    r.encoding = 'UTF-8'
                    how_to_cite = r.text.strip()
                    if r.status_code == 200:
                        print(f"Response: {how_to_cite}")
                        article.custom_how_to_cite = how_to_cite
                        article.save()
                        print(f"Article #{article.pk} how to cite updated.")
                    else:
                        print(f"Crossref API responded with: {r.status_code}")
                except Exception as e:
                    errors.append(
                        {'article': article, 'error': e}
                    )
            else:
                print(f"Article #{article.pk} does not have a DOI")

            time.sleep(2)

        print('Errors:')
        pprint(errors)

