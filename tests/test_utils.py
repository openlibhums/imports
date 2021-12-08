"""
Test cases for utils in imports plugin

Run with
python manage.py test --keepdb imports.tests.test_utils

Debug with
from nose.tools import set_trace; set_trace()

"""

from django.test import TestCase

from plugins.imports import utils
from core import models as core_models
from submission import models as submission_models
from journal import models as journal_models
from utils.testing import helpers
from utils.shared import clear_cache

from django.http import HttpRequest
import csv
import io
import re

CSV_DATA_1 = """Article title,Article abstract,Keywords,License,Language,Author Salutation,Author surname,Author given name,Author middle name,Author email,Author institution,Author is primary (Y/N),Author ORCID,Article ID,DOI,DOI (URL form),Date accepted,Date published,Article section,Stage,Article filename,Journal Code,Journal title,ISSN,Volume number,Issue number,Issue name,Issue pub date
Variopleistocene Inquilibriums,How it all went down.,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Person3,Unreal,J.,unrealperson3@example.com,University of Michigan Medical School,Y,,,,,2021-10-24,2021-10-25,Article,Editor Copyediting,,TST,Journal One,0000-0000,1,1,Fall 2021,2021-09-15 13:58:59+0000
,,,,,,Person5,Unreal,J.,unrealperson5@example.com,University of Calgary,N,,,,,,,,,,,,,,,,
,,,,,,Person6,Unreal,J.,unrealperson6@example.com,University of Mars,N,,,,,,,,,,,,,,,,
"""


MOCK_REQUEST = HttpRequest()

# Utils


def run_import(csv_string):
    """
    Simulates the import
    """

    reader = csv.DictReader(csv_string.splitlines())
    zip_folder_path = "test_zip_1.zip"

    errors, actions = utils.update_article_metadata(
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
        'Article abstract': article.abstract,
        'Keywords': ",".join([str(kw) for kw in article.keywords.all()]),
        'License': str(article.license),
        'Language': article.language,
        #  author columns will go here
        'Article ID': str(article.id),
        'DOI': article.get_doi(),
        'DOI (URL form)': 'https://doi.org/' + article.get_doi(
            ) if article.get_doi() else None,
        'Date accepted': article.date_accepted.strftime(
            '%Y-%m-%d') if article.date_accepted else None,
        'Date published': article.date_published.strftime(
            '%Y-%m-%d') if article.date_published else None,
        'Article section': article.section.name,
        'Stage': article.stage,
        'Article filename': None,
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

    author_data = {
        'Author Salutation': frozen_author.author.salutation,
        'Author surname': frozen_author.last_name,
        'Author given name': frozen_author.first_name,
        'Author middle name': frozen_author.middle_name,
        'Author email': frozen_author.author.email,
        'Author institution': frozen_author.institution,
        'Author is primary (Y/N)': 'Y' if (
            frozen_author.author == article.correspondence_author
        ) else 'N',
        'Author ORCID': 'https://orcid.org/' + str(
            frozen_author.author.orcid
        ) if frozen_author.author.orcid else None,
    }

    return author_data


class TestUpdateArticleMetadata(TestCase):
    @classmethod
    def setUpTestData(cls):

        journal_one, journal_two = helpers.create_journals()
        issue_type = journal_models.IssueType.objects.get_or_create(
            journal=journal_one,
            code='issue'
        )

        test_user = helpers.create_user(username='unrealperson12@example.com')
        MOCK_REQUEST.user = test_user

        csv_data_2 = CSV_DATA_1
        run_import(csv_data_2)

    def tearDown(self):
        reset_csv_data = CSV_DATA_1.replace(
            'University of Michigan Medical School,Y,,,,,',
            'University of Michigan Medical School,Y,,1,,,'
        )
        run_import(reset_csv_data)

        article_2 = submission_models.Article.objects.filter(id=2).first()
        if article_2:
            article_2.delete()

    def test_update_article_metadata_fresh_import(self):
        """
        Whether the attributes of the article were
        saved correctly on first import.
        """

        # add article id to expected data
        csv_data_2 = CSV_DATA_1.replace(
            'University of Michigan Medical School,Y,,,,,',
            'University of Michigan Medical School,Y,,1,,,'  # article id
        )

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1)

        self.assertEqual(csv_data_2, saved_article_data)

    def test_update_article_metadata_update(self):

        clear_cache()

        # change article data
        csv_data_3 = CSV_DATA_1.replace(
            'Variopleistocene Inquilibriums,How it all went down.,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Person3,Unreal,J.,unrealperson3@example.com,University of Michigan Medical School,Y,,,,,2021-10-24,2021-10-25',
            'Multipleistocene Exquilibriums,How it is still going down.,"better dinosaurs,worse teaching",CC BY 4.0,French,Prof,Person3,Unreal,J.,unrealperson3@example.com,University of Michigan Medical School,Y,,1,10.1234/tst.1,https://doi.org/10.1234/tst.1,2021-10-25,2021-10-26'
        )

        run_import(csv_data_3)

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1)
        self.assertEqual(csv_data_3, saved_article_data)

    def test_empty_fields(self):
        """
        Tests whether Janeway accepts null values for nonrequired fields
        """

        clear_cache()

        # blank out non-required rows
        csv_data_12 = CSV_DATA_1.replace(
            'Variopleistocene Inquilibriums,How it all went down.,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Person3,Unreal,J.,unrealperson3@example.com,University of Michigan Medical School,Y,,,,,2021-10-24,2021-10-25,Article,Editor Copyediting,,TST,Journal One,0000-0000,1,1,Fall 2021,2021-09-15 13:58:59+0000',
            'Variopleistocene Inquilibriums,,,,,,,,,,,Y,,,,,,,Article,,,TST,Journal One,,,,,2021-09-15 13:58:59+0000'
        )

        # add article id to expected data
        csv_data_12 = csv_data_12.replace(
            ',,,,,,,,,,,Y,,,,,,,Article,,,TST,Journal One,,,,,2021-09-15 13:58:59+0000',
            ',,,,,,,,,,,Y,,2,,,,,Article,Unassigned,,TST,Journal One,0000-0000,0,0,,2021-09-15 13:58:59+0000'
        )

        run_import(csv_data_12)
        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2)

        # account for uuid4-generated email address
        saved_article_data = re.sub(
            '[a-z0-9\-]{36}@journal\.com',
            '',
            saved_article_data
        )

        self.assertEqual(csv_data_12, saved_article_data)

    def test_update_with_empty(self):
        """
        Tests whether Janeway properly interprets blank fields on update
        """

        clear_cache()

        original_row = 'Variopleistocene Inquilibriums,How it all went down.,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Person3,Unreal,J.,unrealperson3@example.com,University of Michigan Medical School,Y,,,,,2021-10-24,2021-10-25,Article,Editor Copyediting,,TST,Journal One,0000-0000,1,1,Fall 2021,2021-09-15 13:58:59+0000'

        # put something in every cell so you can test importing blanks
        fully_populated_row = 'Variopleistocene Inquilibriums,How it all went down.,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Person3,Unreal,J.,unrealperson3@example.com,University of Michigan Medical School,Y,https://orcid.org/0000-1234-5578-901X,1,10.1234/tst.1,https://doi.org/10.1234/tst.1,2021-10-24,2021-10-25,Article,Editor Copyediting,,TST,Journal One,0000-0000,1,1,Fall 2021,2021-09-15 13:58:59+0000'

        csv_data_13 = CSV_DATA_1.replace(
            original_row,
            fully_populated_row
        )
        run_import(csv_data_13)

        # blank out non-required rows to test import
        updated_row_with_blanks_to_test = 'Variopleistocene Inquilibriums,,,,,,,,,unrealperson3@example.com,,Y,,1,,,,,Article,Editor Copyediting,,TST,Journal One,,1,1,,2021-09-15 13:58:59+0000'

        csv_data_13 = csv_data_13.replace(
            fully_populated_row,
            updated_row_with_blanks_to_test
        )
        run_import(csv_data_13)

        # account for blanks in import data that aren't saved to db
        expected_row_from_saved_data = 'Variopleistocene Inquilibriums,,,,,Prof,,,,unrealperson3@example.com,,Y,,1,10.1234/tst.1,https://doi.org/10.1234/tst.1,,,Article,Editor Copyediting,,TST,Journal One,0000-0000,1,1,,2021-09-15 13:58:59+0000'

        csv_data_13 = csv_data_13.replace(
            updated_row_with_blanks_to_test,
            expected_row_from_saved_data
        )

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1)

        # account for uuid4-generated email address
        saved_article_data = re.sub(
            '[a-z0-9\-]{36}@journal\.com',
            '',
            saved_article_data
        )

        self.assertEqual(csv_data_13, saved_article_data)

    def test_prepare_reader_rows(self):

        # add article id to test update
        csv_data_8 = CSV_DATA_1.replace(
            'University of Michigan Medical School,Y,,,,,',
            'University of Michigan Medical School,Y,,1,,,'  # article id
        )

        reader = csv.DictReader(csv_data_8.splitlines())
        article_groups = utils.prepare_reader_rows(reader)

        reader_rows = [r for r in csv.DictReader(csv_data_8.splitlines())]

        expected_article_groups = [{
            'type': 'Update',
            'primary_row': reader_rows[0],
            'author_rows': [reader_rows[1], reader_rows[2]],
            'primary_row_number': 0,
            'article_id': '1',
        }]
        self.assertEqual(expected_article_groups, article_groups)

    def test_prep_update(self):

        # add article id to test update
        csv_data_8 = CSV_DATA_1.replace(
            'University of Michigan Medical School,Y,,,,,',
            'University of Michigan Medical School,Y,,1,,,'  # article id
        )

        reader = csv.DictReader(csv_data_8.splitlines())
        prepared_reader_row = utils.prepare_reader_rows(reader)[0]
        journal, article, issue_type, issue = utils.prep_update(
            prepared_reader_row.get('primary_row')
        )

        returned_data = [
            journal.code,
            article.title,
            issue_type.code,
            issue.volume,
        ]

        expected_data = [
            'TST',
            'Variopleistocene Inquilibriums',
            'issue',
            1
        ]

        self.assertEqual(expected_data, returned_data)

    def test_update_keywords(self):

        clear_cache()

        article_1 = submission_models.Article.objects.get(id=1)

        keywords = ['better dinosaurs', 'worse teaching']
        utils.update_keywords(keywords, article_1)
        saved_keywords = [str(w) for w in article_1.keywords.all()]
        self.assertEqual(keywords, saved_keywords)

    def test_user_becomes_owner(self):

        clear_cache()

        article_1 = submission_models.Article.objects.get(id=1)
        self.assertEqual(MOCK_REQUEST.user.email, article_1.owner.email)

    def test_changes_to_issue(self):

        clear_cache()

        # change article id
        csv_data_11 = CSV_DATA_1.replace(
            'Y,,,,,2021-10-24',
            'Y,,2,,,2021-10-24'
        )

        # change issue name and date
        csv_data_11 = csv_data_11.replace(
            'Fall 2021,2021-09-15 13:58:59+0000',
            'Winter 2022,2022-01-15 13:58:59+0000'
        )

        run_import(csv_data_11)

        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2)

        self.assertEqual(csv_data_11, saved_article_data)

    def test_changes_to_author_fields(self):

        clear_cache()

        # change data for unrealperson3@example.com
        # add article id
        csv_data_4 = CSV_DATA_1.replace(
            'Prof,Person3,Unreal,J.,unrealperson3@example.com,University of Michigan Medical School,Y,,',
            'Prof,Personne3,Surreal,J.,unrealperson3@example.com,University of Toronto,N,https://orcid.org/0000-1234-5678-901X,1'
        )

        # make unrealperson6@example.com primary
        csv_data_4 = csv_data_4.replace(
            ',,,,,,Person6,Unreal,J.,unrealperson6@example.com,University of Mars,N,,,,,,,,,,,,,,,,',
            ',,,,,,Person6,Unreal,J.,unrealperson6@example.com,University of Mars,Y,,,,,,,,,,,,,,,,'
        )

        # remove unrealperson5@example.com
        csv_data_4 = csv_data_4.replace(
            '''
,,,,,,Person5,Unreal,J.,unrealperson5@example.com,University of Calgary,N,,,,,,,,,,,,,,,,''',
            ''
        )
        run_import(csv_data_4)

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1)

        self.assertEqual(csv_data_4, saved_article_data)

    def test_update_frozen_author(self):

        clear_cache()

        article_1 = submission_models.Article.objects.get(id=1)

        author_fields = [
            'Prof',  # salutation is not currently
                     # an attribute of FrozenAuthor
            'Surreal',
            'J.',
            'Personne',
            'University of Toronto',
            '',      # bio not in import template
            'unrealperson6@example.com'
        ]

        utils.update_frozen_author(author_fields, article_1)
        author = core_models.Account.objects.get(email=author_fields[6])
        frozen_author = author.frozen_author(article_1)

        saved_fields = [
            'Prof',
            frozen_author.first_name,
            frozen_author.middle_name,
            frozen_author.last_name,
            frozen_author.institution,
            '',
            frozen_author.author.email
        ]

        self.assertEqual(author_fields, saved_fields)

    def test_changes_to_section(self):

        clear_cache()

        # add article id
        # change section
        csv_data_5 = CSV_DATA_1.replace(
            ',,,,,2021-10-24,2021-10-25,Article,',
            ',,1,,,2021-10-24,2021-10-25,Interview,'
            )

        run_import(csv_data_5)

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1)
        self.assertEqual(csv_data_5, saved_article_data)

    def test_different_stages(self):

        clear_cache()

        # import "new" article with different section
        csv_data_6 = CSV_DATA_1.replace(
            'Y,,,,,,,Article,Editor Copyediting',
            'Y,,,,,,,Article,Typesetting Plugin'
        )

        run_import(csv_data_6)

        # add article id
        csv_data_6 = csv_data_6.replace(
            'Y,,',
            'Y,,2'
        )

        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2)
        self.assertEqual(csv_data_6, saved_article_data)

    def test_bad_data(self):

        clear_cache()

        csv_data_7 = """Article title,Article abstract,Keywords,License,Language,Author Salutation,Author surname,Author given name,Author middle name,Author email,Author institution,Author is primary (Y/N),Author ORCID,Article ID,DOI,DOI (URL form),Date accepted,Date published,Article section,Stage,Article filename,Journal Code,Journal title,ISSN,Volume number,Issue number,Issue name,Issue pub date
£$^^£&&££&££££$,;;;;;;,2fa09srh14!$,£%^^£&,%^*%^&*%^&*,$*^%*^%*&,%^*%&*,2f0SD)F*,%^&*%^&*,%^&*%^UY,$^&*^%&(^%()),%^&(&^%()),https://orcid.org/n0ns3ns3,,,,,,$%^&$%^&$%*,Editor Copyediting,,TST,Journal One,0000-0000,0,0,20432%^&RIY$%*RI,2021-09-15 13:58:59+0000
"""

        # Note: Not all of the above should not be importable,
        # esp. the email and orcid

        run_import(csv_data_7)

        # add article id
        # account for human-legible N for non corresondence author
        csv_data_7 = csv_data_7.replace(
            '%^&(&^%()),https://orcid.org/n0ns3ns3,',
            'N,https://orcid.org/n0ns3ns3,2'
        )

        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2)
        self.assertEqual(csv_data_7, saved_article_data)

    def test_data_with_whitespace(self):

        clear_cache()

        csv_data_9 = CSV_DATA_1.replace(
            'Variopleistocene Inquilibriums,How it all went down.,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Person3,Unreal,J.,unrealperson3@example.com,University of Michigan Medical School,,Y,,,,2021-10-24,2021-10-25,Article,Editor Copyediting,,TST,Journal One,0000-0000,1,1,Fall 2021,2021-09-15 13:58:59+0000',
            ' Variopleistocene Inquilibriums ,  How it all went down.  ,"       dinosaurs,Socratic teaching",  CC BY-NC-SA 4.0 ,     English  ,    Prof    ,Person3    ,   Unreal  , J. , unrealperson3@example.com  ,  University of Michigan Medical School,  , Y , , , , 2021-10-24                , 2021-10-25,  Article , Editor Copyediting   , , TST ,  Journal One ,   0000-0000 , 1 , 1 , Fall 2021  ,      2021-09-15 13:58:59+0000 '
        )

        run_import(csv_data_9)

        # add article id
        csv_data_10 = CSV_DATA_1.replace(
            'University of Michigan Medical School,Y,,',
            'University of Michigan Medical School,Y,,2'
        )

        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2)
        self.assertEqual(csv_data_10, saved_article_data)
