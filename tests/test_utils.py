"""
Test cases for utils in imports plugin

Run with
python manage.py test --keepdb imports.tests.test_utils

Debug with
from nose.tools import set_trace; set_trace()

"""
from django.test import TestCase

from plugins.imports import utils
from submission import models as submission_models
from journal import models as journal_models
from utils.testing import helpers

from django.http import HttpRequest
import csv
import io


CSV_DATA_1 = """Article title,Keywords,License,Language,Author Salutation,Author surname,Author given name,Author email,Author institution,Author is primary (Y/N),Author ORCID,Article ID,DOI,DOI (URL form),Date accepted,Date published,Article section,Stage,Article filename,Article sequence,Journal Code,Journal title,ISSN,Volume number,Issue number,Issue name,Issue pub date
Variopleistocene Inquilibriums,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Person3,Unreal,unrealperson3@example.com,University of Michigan Medical School,Y,,,,,,,Article,Editor Copyediting,,,TST,Journal One,0000-0000,1,1,,2021-09-15 13:58:59+0000
,,,,,Person5,Unreal,unrealperson5@example.com,University of Calgary,N,,,,,,,,,,,,,,,,,
,,,,,Person6,Unreal,unrealperson6@example.com,University of Mars,N,,,,,,,,,,,,,,,,,
"""


CSV_DATA_2 = """Article title,Keywords,License,Language,Author Salutation,Author surname,Author given name,Author email,Author institution,Author is primary (Y/N),Author ORCID,Article ID,DOI,DOI (URL form),Date accepted,Date published,Article section,Stage,Article filename,Article sequence,Journal Code,Journal title,ISSN,Volume number,Issue number,Issue name,Issue pub date
Variopleistocene Inquilibriums,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Person3,Unreal,unrealperson3@example.com,University of Michigan Medical School,Y,https://orcid.org/0000-1234-5678-901X,,,,2021-07-15,2021-08-31,Article,Editor Copyediting,,,TST,Journal One,0000-0000,1,1,,2021-09-15 13:58:59+0000
"Parsimonious Undulation, Univariant Echoes, and the Theory of the Decibel","echoes,decibel,cheapness,young adults",CC BY-NC-SA 4.0,English,,Person4,Unreal,unrealperson4@example.com,"University of Michigan School of Public Health, Department of Environmental Health Sciences",Y,https://orcid.org/0000-2345-6789-0123,,,,2021-07-15,2021-08-31,Article,Editor Copyediting,,,TST,Journal One,0000-0000,1,1,,2021-08-31 13:58:59+0000
"""

MOCK_REQUEST = HttpRequest()

# Utils

def run_import(csv_string):
    """
    Simulates the import
    """

    reader = csv.DictReader(csv_string.splitlines())
    zip_folder_path = "test_zip_1.zip"

    utils.update_article_metadata(
        MOCK_REQUEST,
        reader,
        zip_folder_path,
    )


def read_saved_article_data(article):
    """
    Gets saved article data from the database for comparison
    with the expected article data
    """

    main_row = {
        'Article title': article.title,
        'Keywords': ",".join([str(kw) for kw in article.keywords.all()]),
        'License': str(article.license),
        'Language': article.language,
        #  author columns will go here
        'Article ID': str(article.id),
        'DOI': article.get_doi(),
        'DOI (URL form)': 'https://doi.org/'+article.get_doi(
            ) if article.get_doi() else None,
        'Date accepted': article.date_accepted.strftime(
            '%Y-%m-%d') if article.date_accepted else None,
        'Date published': article.date_published.strftime(
            '%Y-%m-%d') if article.date_published else None,
        'Article section': article.section.name,
        'Stage': article.stage,
        'Article filename': None,
        'Article sequence': None,
        'Journal Code': article.journal.code,
        'Journal title': article.journal.name,
        'ISSN': article.journal.issn,
        'Volume number': article.issue.volume,
        'Issue number': article.issue.issue,
        'Issue name': article.issue.issue_title,
        'Issue pub date': article.issue.date.strftime('%Y-%m-%d %H:%M:%S%z')
    }

    author_rows = {}

    for frozen_author in article.frozenauthor_set.all():
        order = frozen_author.order
        author_rows[order] = read_saved_frozen_author_data(
            frozen_author,
            article
        )

    # transfer first author row into main article row
    for k, v in author_rows.pop(0).items():
        main_row[k] = v

    with io.StringIO() as mock_csv_file:

        fieldnames = CSV_DATA_1.splitlines()[0].split(',')

        dialect = csv.excel()
        dialect.lineterminator = '\n'
        dialect.quoting = csv.QUOTE_MINIMAL

        writer = csv.DictWriter(
            mock_csv_file,
            fieldnames=fieldnames,
            dialect=dialect,
        )
        writer.writeheader()
        writer.writerow(main_row)

        # write subsequent author rows
        for order in sorted(list(author_rows.keys())):
            writer.writerow(author_rows[order])

        csv_string = mock_csv_file.getvalue()

    return csv_string

def read_saved_frozen_author_data(frozen_author, article):
    """
    Gets saved account data from the database for comparison
    with the expected account data
    """

    return {
        'Author Salutation': frozen_author.author.salutation,
        'Author surname': frozen_author.last_name,
        'Author given name': frozen_author.first_name,
        'Author email': frozen_author.author.email,
        'Author institution': frozen_author.institution,
        'Author is primary (Y/N)': 'Y' if (
            frozen_author.author == article.correspondence_author
        ) else 'N',
        'Author ORCID': None,  # not desired behavior
    }


class TestUpdateArticleMetadata(TestCase):
    @classmethod
    def setUpTestData(cls):

        journal_one, journal_two = helpers.create_journals()
        issue_type = journal_models.IssueType.objects.get_or_create(
            journal=journal_one,
            code='issue'
        )

        current_user = helpers.create_user('unrealperson2@example.com')
        current_user.first_name = 'Unreal'
        current_user.last_name = 'Person2'
        MOCK_REQUEST.user = current_user

        run_import(CSV_DATA_1)

    def testNewArticleImportData(self):
        """
        Whether the attributes of the article were
        saved correctly on first import.
        """

        global CSV_DATA_1
        # add article id to expected data
        CSV_DATA_1 = CSV_DATA_1.replace(
            'University of Michigan Medical School,Y,,,,,',
            'University of Michigan Medical School,Y,,1,,,'  # article id
        )

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1)

        self.assertEqual(CSV_DATA_1, saved_article_data)

    def testChangesToArticleMetadata(self):
        csv_data_3 = """Article title,Keywords,License,Language,Author Salutation,Author surname,Author given name,Author email,Author institution,Author is primary (Y/N),Author ORCID,Article ID,DOI,DOI (URL form),Date accepted,Date published,Article section,Stage,Article filename,Article sequence,Journal Code,Journal title,ISSN,Volume number,Issue number,Issue name,Issue pub date
Multipleistocene Exquilibriums,"better dinosaurs,worse teaching",CC BY 4.0,French,Prof,Person3,Unreal,unrealperson3@example.com,University of Michigan Medical School,Y,,1,10.1234/tst.1,https://doi.org/10.1234/tst.1,,,Article,Editor Copyediting,,,TST,Journal One,0000-0000,1,1,,2021-09-15 13:58:59+0000
,,,,,Person5,Unreal,unrealperson5@example.com,University of Calgary,N,,,,,,,,,,,,,,,,,
,,,,,Person6,Unreal,unrealperson6@example.com,University of Mars,N,,,,,,,,,,,,,,,,,
"""

        run_import(csv_data_3)

        # add old keywords back in to expected_data
        # not desired behavior
        csv_data_3 = csv_data_3.replace(
            'better dinosaurs,worse teaching',
            'dinosaurs,Socratic teaching,better dinosaurs,worse teaching'
        )

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1)
        self.assertEqual(csv_data_3, saved_article_data)

    def testChangesToAuthorMetadata(self):
        csv_data_4 = """Article title,Keywords,License,Language,Author Salutation,Author surname,Author given name,Author email,Author institution,Author is primary (Y/N),Author ORCID,Article ID,DOI,DOI (URL form),Date accepted,Date published,Article section,Stage,Article filename,Article sequence,Journal Code,Journal title,ISSN,Volume number,Issue number,Issue name,Issue pub date
Variopleistocene Inquilibriums,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Personne3,Surreal,unrealperson3@example.com,University of Toronto,N,https://orcid.org/0000-1234-5678-901X,1,,,,,Article,Editor Copyediting,,,TST,Journal One,0000-0000,1,1,,2021-09-15 13:58:59+0000
,,,,,Person5,Unreal,unrealperson5@example.com,University of Calgary,N,,,,,,,,,,,,,,,,,
,,,,,Person6,Unreal,unrealperson6@example.com,University of Mars,Y,,,,,,,,,,,,,,,,,
"""

        run_import(csv_data_4)

        # change name back in expected data
        # not desired behavior
        csv_data_4 = csv_data_4.replace('Personne3,Surreal', 'Person3,Unreal')

        # change institution back in expected data
        # not desired behavior
        csv_data_4 = csv_data_4.replace('Toronto', 'Michigan Medical School')

        # remove orcid in expected data
        # not desired behavior
        csv_data_4 = csv_data_4.replace(
            'https://orcid.org/0000-1234-5678-901X',
            ''
        )

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1)
        self.assertEqual(csv_data_4, saved_article_data)
