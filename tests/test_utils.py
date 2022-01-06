from django.test import TestCase

from plugins.imports import utils, export, views
from core import models as core_models
from submission import models as submission_models
from journal import models as journal_models
from utils.testing import helpers
from utils.shared import clear_cache

from datetime import datetime
from django.utils.timezone import make_aware, utc
from rest_framework import routers
from django.http import HttpRequest
import csv
import io
import re
import zipfile
import os

CSV_DATA_1 = """Article title,Article abstract,Keywords,License,Language,Author Salutation,Author given name,Author middle name,Author surname,Author email,Author ORCID,Author institution,Author department,Author biography,Author is primary (Y/N),Author is corporate (Y/N),Article ID,DOI,DOI (URL form),Date accepted,Date published,Article section,Stage,File import identifier,Journal Code,Journal title,ISSN,Volume number,Issue number,Issue name,Issue pub date
Variopleistocene Inquilibriums,How it all went down.,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Unreal,J.,Person3,unrealperson3@example.com,https://orcid.org/0000-1234-5578-901X,University of Michigan Medical School,Cancer Center,Prof Unreal J. Person3 teaches dinosaurs but they are employed in a hospital.,Y,N,,,,2021-10-24T10:24:00+00:00,2021-10-25T10:25:25+00:00,Article,Editor Copyediting,,TST,Journal One,0000-0000,1,1,Fall 2021,2021-09-15T09:15:15+00:00
,,,,,,Unreal,J.,Person5,unrealperson5@example.com,,University of Calgary,Anthropology,Unreal J. Person5 is the author of <i>Being</i>.,N,N,,,,,,,,,,,,,,,
,,,,,,Unreal,J.,Person6,unrealperson6@example.com,,University of Mars,Crater Nine,Does Unreal J. Person6 exist?,N,N,,,,,,,,,,,,,,,
"""



# Utils


def run_import(csv_string, mock_request, path_to_zip=None):
    """
    Simulates the import
    """

    reader = csv.DictReader(csv_string.splitlines())
    if path_to_zip:
        _path, zip_folder_path, _errors = utils.prep_update_file(path_to_zip)
    else:
        zip_folder_path = ''

    errors, actions = utils.update_article_metadata(
        mock_request,
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
        'Date accepted': article.date_accepted.isoformat() if article.date_accepted else None,
        'Date published': article.date_published.isoformat() if article.date_published else None,
        'Article section': article.section.name,
        'Stage': article.stage,
        'File import identifier': None,
        # read_saved_files needs updating
        # 'File import identifier': read_saved_files(article),
        'Journal Code': article.journal.code,
        'Journal title': article.journal.name,
        'ISSN': article.journal.issn,
        'Volume number': article.issue.volume if article.issue else None,
        'Issue number': article.issue.issue if article.issue else None,
        'Issue name': article.issue.issue_title if article.issue else None,
        'Issue pub date': article.issue.date.isoformat() if article.issue else None,
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

def read_saved_files(article):
    filenames = [f.original_filename for f in article.manuscript_files.all()]
    filenames.extend([f.original_filename for f in article.data_figure_files.all()])
    return ','.join([f'{article.pk}/{filename}' for filename in sorted(filenames)])

def read_saved_frozen_author_data(frozen_author, article):
    """
    Gets saved frozen author data from the database for comparison
    with the expected frozen author data
    """

    frozen_author_data = {
        'Author Salutation': frozen_author.author.salutation if frozen_author.author else None,
        'Author given name': frozen_author.first_name,
        'Author middle name': frozen_author.middle_name,
        'Author surname': frozen_author.last_name,
        'Author email': frozen_author.author.email if frozen_author.author else None,
        'Author ORCID': 'https://orcid.org/' + frozen_author.frozen_orcid if (
            frozen_author.frozen_orcid
        ) else None,
        'Author institution': frozen_author.institution,
        'Author department': frozen_author.department,
        'Author biography': frozen_author.frozen_biography,
        'Author is primary (Y/N)': 'Y' if frozen_author.author and (
            frozen_author.author == article.correspondence_author
        ) else 'N',
        'Author is corporate (Y/N)': 'Y' if frozen_author.is_corporate else 'N',
    }

    return frozen_author_data

def read_saved_author_data(author):
    """
    Gets author data from the database for comparison
    with the exptected author data
    """

    author_data = {
        author.salutation,
        author.first_name,
        author.middle_name,
        author.last_name,
        author.email,
        author.orcid,
        author.institution,
        author.department,
        author.biography,
    }

    return author_data


def make_import_zip(
        test_data_path,
        article_data_csv,
        csv_filename = 'article_data.csv',
    ):
    if not os.path.exists(test_data_path):
        os.mkdir(test_data_path)

    managepy_dir = os.getcwd()
    os.chdir(test_data_path)
    with zipfile.ZipFile('import.zip', 'w') as import_zip:
        for subdir, dirs, files in os.walk('.'):
            for filename in files:
                filepath = os.path.join(subdir, filename)
                if not filepath.endswith('.zip'):
                    import_zip.write(filepath)
        import_zip.writestr(
            zipfile.ZipInfo(filename=csv_filename),
            article_data_csv,
        )
    os.chdir(managepy_dir)
    path_to_zip = os.path.join(test_data_path, 'import.zip')
    return path_to_zip

def clear_import_zips():
    test_data_path = os.path.join('plugins','imports','tests','test_data')
    for subdir, dirs, files in os.walk(test_data_path):
        for filename in files:
            filepath = subdir + os.sep + filename
            if filepath.endswith('.zip'):
                os.remove(filepath)
            elif filepath.endswith('.csv'):
                os.remove(filepath)

class TestImportAndUpdate(TestCase):
    @classmethod
    def setUpTestData(cls):

        journal_one, journal_two = helpers.create_journals()
        issue_type = journal_models.IssueType.objects.get_or_create(
            journal=journal_one,
            code='issue'
        )

        cls.mock_request = HttpRequest()
        cls.test_user = helpers.create_user(username='unrealperson12@example.com')
        cls.mock_request.user = cls.test_user

        csv_data_2 = CSV_DATA_1
        run_import(csv_data_2, cls.mock_request)

    def tearDown(self):
        reset_csv_data = CSV_DATA_1.replace(
            'Y,N,,,,',
            'Y,N,1,,,'
        )
        run_import(reset_csv_data, self.mock_request)

        article_2 = submission_models.Article.objects.filter(id=2).first()
        if article_2:
            article_2.delete()

        for issue in journal_models.Issue.objects.all():
            issue.delete()

        clear_import_zips()

    def test_update_article_metadata_fresh_import(self):
        """
        Whether the attributes of the article were
        saved correctly on first import.
        """

        # add article id to expected data
        csv_data_2 = CSV_DATA_1.replace(
            'Y,N,,,,',
            'Y,N,1,,,'  # article id
        )

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1)

        self.assertEqual(csv_data_2, saved_article_data)

    def test_update_article_metadata_update(self):

        clear_cache()

        # change article data
        csv_data_3 = CSV_DATA_1.replace(
            'Variopleistocene Inquilibriums,How it all went down.,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Unreal,J.,Person3,unrealperson3@example.com,https://orcid.org/0000-1234-5578-901X,University of Michigan Medical School,Cancer Center,Prof Unreal J. Person3 teaches dinosaurs but they are employed in a hospital.,Y,N,,,,2021-10-24T10:24:00+00:00,2021-10-25T10:25:25+00:00',
            'Multipleistocene Exquilibriums,How it is still going down.,"better dinosaurs,worse teaching",CC BY 4.0,French,Prof,Unreal,J.,Person3,unrealperson3@example.com,https://orcid.org/0000-1234-5578-901X,University of Michigan Medical School,Cancer Center,Prof Unreal J. Person3 teaches dinosaurs but they are employed in a hospital.,Y,N,1,10.1234/tst.1,https://doi.org/10.1234/tst.1,2021-10-25T10:25:25+00:00,2021-10-26T10:26:00+00:00'
        )

        run_import(csv_data_3, self.mock_request)

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
            'Variopleistocene Inquilibriums,How it all went down.,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Unreal,J.,Person3,unrealperson3@example.com,https://orcid.org/0000-1234-5578-901X,University of Michigan Medical School,Cancer Center,Prof Unreal J. Person3 teaches dinosaurs but they are employed in a hospital.,Y,N,,,,2021-10-24T10:24:00+00:00,2021-10-25T10:25:25+00:00,Article,Editor Copyediting,,TST,Journal One,0000-0000,1,1,Fall 2021,2021-09-15T09:15:15+00:00',
            'Variopleistocene Inquilibriums,,,,,,,,,,,,,,Y,N,,,,,,Article,,,TST,Journal One,,,,,2021-09-15T09:15:15+00:00'
        )

        # add article id and a few other sticky things back to expected data
        csv_data_12 = csv_data_12.replace(
            'Variopleistocene Inquilibriums,,,,,,,,,,,,,,Y,N,,,,,,Article,,,TST,Journal One,,,,,2021-09-15T09:15:15+00:00',
            'Variopleistocene Inquilibriums,,,,,,,,,,,,,,Y,N,2,,,,,Article,Unassigned,,TST,Journal One,0000-0000,0,0,,2021-09-15T09:15:15+00:00'
        )
        run_import(csv_data_12, self.mock_request)
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

        original_row = 'Variopleistocene Inquilibriums,How it all went down.,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Unreal,J.,Person3,unrealperson3@example.com,https://orcid.org/0000-1234-5578-901X,University of Michigan Medical School,Cancer Center,Prof Unreal J. Person3 teaches dinosaurs but they are employed in a hospital.,Y,N,,,,2021-10-24T10:24:00+00:00,2021-10-25T10:25:25+00:00,Article,Editor Copyediting,,TST,Journal One,0000-0000,1,1,Fall 2021,2021-09-15T09:15:15+00:00'

        # put something in every cell so you can test importing blanks
        fully_populated_row = 'Variopleistocene Inquilibriums,How it all went down.,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Unreal,J.,Person3,unrealperson3@example.com,https://orcid.org/0000-1234-5578-901X,University of Michigan Medical School,Cancer Center,Prof Unreal J. Person3 teaches dinosaurs but they are employed in a hospital.,Y,N,1,10.1234/tst.1,https://doi.org/10.1234/tst.1,2021-10-24T10:24:00+00:00,2021-10-25T10:25:25+00:00,Article,Editor Copyediting,,TST,Journal One,0000-0000,1,1,Fall 2021,2021-09-15T09:15:15+00:00'

        csv_data_13 = CSV_DATA_1.replace(
            original_row,
            fully_populated_row
        )
        run_import(csv_data_13, self.mock_request)

        # blank out non-required rows to test import
        updated_row_with_blanks_to_test = 'Variopleistocene Inquilibriums,,,,,,,,,unrealperson3@example.com,,,,,Y,,1,,,,,Article,Editor Copyediting,,TST,Journal One,,1,1,,2021-09-15T09:15:15+00:00'

        csv_data_13 = csv_data_13.replace(
            fully_populated_row,
            updated_row_with_blanks_to_test
        )
        run_import(csv_data_13, self.mock_request)

        # account for blanks in import data that aren't saved to db
        expected_row_from_saved_data = 'Variopleistocene Inquilibriums,,,,,Prof,,,,unrealperson3@example.com,,,,,Y,N,1,10.1234/tst.1,https://doi.org/10.1234/tst.1,,,Article,Editor Copyediting,,TST,Journal One,0000-0000,1,1,,2021-09-15T09:15:15+00:00'

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
            'Y,N,',
            'Y,N,1'  # article id
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
            'Y,N,',
            'Y,N,1'  # article id
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
        self.assertEqual(self.mock_request.user.email, article_1.owner.email)

    def test_changes_to_issue(self):

        clear_cache()

        # change article id
        csv_data_11 = CSV_DATA_1.replace(
            'Y,N,,,,2021-10-24T10:24:00+00:00',
            'Y,N,2,,,2021-10-24T10:24:00+00:00'
        )

        # change issue name and date
        csv_data_11 = csv_data_11.replace(
            'Fall 2021,2021-09-15T09:15:15+00:00',
            'Winter 2022,2022-01-15T01:15:15+00:00'
        )

        run_import(csv_data_11, self.mock_request)

        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2)

        self.assertEqual(csv_data_11, saved_article_data)

    def test_changes_to_author_fields(self):

        clear_cache()

        # change data for unrealperson3@example.com
        # add article id
        csv_data_4 = CSV_DATA_1.replace(
            'Prof,Unreal,J.,Person3,unrealperson3@example.com,https://orcid.org/0000-1234-5578-901X,University of Michigan Medical School,Cancer Center,Prof Unreal J. Person3 teaches dinosaurs but they are employed in a hospital.,Y,N,',
            'Prof,Surreal,J.,Personne3,unrealperson3@example.com,https://orcid.org/0000-1234-5678-909X,University of Toronto,Children\'s Center,Many are the accomplishments of Surreal Personne3,N,N,1'
        )

        # make unrealperson6@example.com primary
        csv_data_4 = csv_data_4.replace(
            'Does Unreal J. Person6 exist?,N,N',
            'Does Unreal J. Person6 exist?,Y,N'
        )

        # remove unrealperson5@example.com
        csv_data_4 = csv_data_4.replace(
            '''
,,,,,,Unreal,J.,Person5,unrealperson5@example.com,,University of Calgary,Anthropology,Unreal J. Person5 is the author of <i>Being</i>.,N,N,,,,,,,,,,,,,,,''',
            ''
        )
        run_import(csv_data_4, self.mock_request)

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
            'Department of Sociology',
            'Many things have been written by and about this human.',
            'unrealperson6@example.com',
            '3675-1824-2638-1859',
            'N',      # author is corporate
            3,
        ]

        author = core_models.Account.objects.get(email=author_fields[7])
        utils.update_frozen_author(author, author_fields, article_1)
        frozen_author = author.frozen_author(article_1)

        saved_fields = [
            'Prof',
            frozen_author.first_name,
            frozen_author.middle_name,
            frozen_author.last_name,
            frozen_author.institution,
            frozen_author.department,
            frozen_author.frozen_biography,
            frozen_author.author.email,
            frozen_author.frozen_orcid,
            'Y' if frozen_author.is_corporate else 'N',
            frozen_author.order,
        ]

        self.assertEqual(author_fields, saved_fields)

    def test_author_accounts_are_linked(self):
        clear_cache()
        article_1 = submission_models.Article.objects.get(id=1)
        saved_author_emails = sorted([a.email for a in article_1.authors.all()])
        expected_author_emails = [
            'unrealperson3@example.com',
            'unrealperson5@example.com',
            'unrealperson6@example.com',
        ]

        self.assertEqual(expected_author_emails, saved_author_emails)

    def test_author_account_data(self):

        clear_cache()

        expected_author_data = {
            'Prof',
            'Unreal',
            'J.',
            'Person3',
            'unrealperson3@example.com',
            '0000-1234-5578-901X',
            'University of Michigan Medical School',
            'Cancer Center',
            'Prof Unreal J. Person3 teaches dinosaurs but they are employed in a hospital.',
        }

        article_1 = submission_models.Article.objects.get(id=1)
        first_author = article_1.authors.all().first()
        saved_author_data = read_saved_author_data(first_author)
        self.assertEqual(expected_author_data, saved_author_data)

    def test_changes_to_section(self):

        clear_cache()

        # add article id
        # change section
        csv_data_5 = CSV_DATA_1.replace(
            'N,,,,2021-10-24T10:24:00+00:00,2021-10-25T10:25:25+00:00,Article,',
            'N,1,,,2021-10-24T10:24:00+00:00,2021-10-25T10:25:25+00:00,Interview,'
        )

        run_import(csv_data_5, self.mock_request)

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1)
        self.assertEqual(csv_data_5, saved_article_data)

    def test_different_stages(self):

        clear_cache()

        # import "new" article with different section
        csv_data_6 = CSV_DATA_1.replace(
            'Y,N,,,,,,Article,Editor Copyediting',
            'Y,N,,,,,,Article,Typesetting Plugin'
        )

        run_import(csv_data_6, self.mock_request)

        # add article id
        csv_data_6 = csv_data_6.replace(
            'Y,N,',
            'Y,N,2'
        )

        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2)
        self.assertEqual(csv_data_6, saved_article_data)

    def test_bad_data(self):

        clear_cache()

        csv_data_7 = """Article title,Article abstract,Keywords,License,Language,Author Salutation,Author given name,Author middle name,Author surname,Author email,Author ORCID,Author institution,Author department,Author biography,Author is primary (Y/N),Author is corporate (Y/N),Article ID,DOI,DOI (URL form),Date accepted,Date published,Article section,Stage,File import identifier,Journal Code,Journal title,ISSN,Volume number,Issue number,Issue name,Issue pub date
Title£$^^£&&££&££££$,Abstract;;;;;;,Keywords2fa09srh14!$,License£%^^£&,Language%^*%^&*%^&*,Salutation$*^%*^%*&,Author given name 2f0SD)F*,Author middle name %^&*%^&*,Author surname %^*%&*,Author email %^&*%^UY,https://orcid.org/n0ns3ns3,Author institution$^&*^%&(^%()),Author department 2043230,Author biography %^&(&^%()),N,gobbledy,,,,,,Section $%^&$%^&$%*,Editor Copyediting,,TST,Journal One,0000-0000,1,1,Issue name 20432%^&RIY$%*RI,2021-09-15T09:15:15+00:00
"""

        # Note: Not all of the above should not be importable,
        # esp. the email and orcid
        run_import(csv_data_7, self.mock_request)

        # add article id
        # account for human-legible N for non corresondence author
        csv_data_7 = csv_data_7.replace(
            'N,gobbledy,',
            'N,N,2'
        )

        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2)
        self.assertEqual(csv_data_7, saved_article_data)

    def test_data_with_whitespace(self):

        clear_cache()

        csv_data_9 = CSV_DATA_1.replace(
            'Variopleistocene Inquilibriums,How it all went down.,"dinosaurs,Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Unreal,J.,Person3,unrealperson3@example.com,,University of Michigan Medical School,Cancer Center,Prof Unreal J. Person3 teaches dinosaurs but they are employed in a hospital.,Y,N,,,,2021-10-24T10:24:00+00:00,2021-10-25T10:25:25+00:00,Article,Editor Copyediting,,TST,Journal One,0000-0000,1,1,Fall 2021,2021-09-15T09:15:15+00:00',
            '   Variopleistocene Inquilibriums   ,   How it all went down.    ,"     dinosaurs,Socratic teaching",    CC BY-NC-SA 4.0,   English,   Prof   ,  Unreal  ,  J.  ,   Person3  ,  unrealperson3@example.com  ,  ,  University of Michigan Medical School ,  Cancer Center  ,   Prof Unreal J. Person3 teaches dinosaurs but they are employed in a hospital.,  Y  ,  N ,   ,  ,  ,  2021-10-24T10:24:00+00:00,  2021-10-25T10:25:25+00:00,   Article,    Editor Copyediting  ,,TST  ,  Journal One  ,0000-0000  ,1  ,  1,  Fall 2021,   2021-09-15T09:15:15+00:00  '
        )

        run_import(csv_data_9, self.mock_request)

        # add article id
        csv_data_10 = CSV_DATA_1.replace(
            'Y,N,',
            'Y,N,2'
        )

        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2)
        self.assertEqual(csv_data_10, saved_article_data)

    def test_corporate_author_import(self):
        clear_cache()

        csv_data_14 = CSV_DATA_1.replace(
            'Prof,Unreal,J.,Person3,unrealperson3@example.com,https://orcid.org/0000-1234-5578-901X,University of Michigan Medical School,Cancer Center,Prof Unreal J. Person3 teaches dinosaurs but they are employed in a hospital.,Y,N',
            ',,,,,,University of Michigan Medical School,,,N,Y'
        )
        run_import(csv_data_14, self.mock_request)

        csv_data_14 = csv_data_14.replace(
            'N,Y,',
            'N,Y,2'  # article id
        )
        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2)
        self.assertEqual(csv_data_14, saved_article_data)

#    def test_handle_file_import(self):
#        clear_cache()
#
#        test_data_path = os.path.join(
#            'plugins',
#            'imports',
#            'tests',
#            'test_data',
#            'test_handle_file_import',
#        )
#
#        csv_data_15 = CSV_DATA_1.replace(
#            'Copyediting,,TST',
#            'Copyediting,"2/2.docx,2/2.pdf,2/2.xml,2/figure1.jpg",TST'
#        )
#        path_to_zip = make_import_zip(
#            test_data_path,
#            csv_data_15,
#        )
#        run_import(csv_data_15, self.mock_request, path_to_zip=path_to_zip)
#        csv_data_15 = csv_data_15.replace(
#            'Y,N,',
#            'Y,N,2'  # article id
#        )
#        article_2 = submission_models.Article.objects.get(id=2)
#        saved_article_data = read_saved_article_data(article_2)
#        self.assertEqual(csv_data_15, saved_article_data)

    def test_article_agreement_set(self):
        article_1 = submission_models.Article.objects.get(id=1)
        self.assertEqual(article_1.article_agreement, 'Imported article')

    def test_get_aware_datetime(self):
        test_timestamps = [
            '2021-12-15',
            '2021-12-15T08:30',
            '2021-12-15T08:30:40+05:00',
        ]

        expected_timestamps = [
            '2021-12-15T12:00:00+00:00',
            '2021-12-15T08:30:00+00:00',
            '2021-12-15T08:30:40+05:00',
        ]

        parsed_timestamps = []
        for timestamp in test_timestamps:
            parsed_timestamps.append(utils.get_aware_datetime(timestamp).isoformat())

        self.assertEqual(expected_timestamps, parsed_timestamps)

    def test_prep_update_file_can_find_zip(self):
        test_data_path = os.path.join(
            'plugins',
            'imports',
            'tests',
            'test_data',
            'test_prep_update_file_with_zip',
        )

        csv_filename = 'can_find_zip.csv'

        path_to_zip = make_import_zip(
            test_data_path,
            CSV_DATA_1,
            csv_filename=csv_filename,
        )

        csv_path, temp_folder_path, errors = utils.prep_update_file(
            path_to_zip
        )

        self.assertEqual(csv_filename, csv_path.split('/')[-1])

    def test_prep_update_file_can_find_csv(self):
        test_data_path = os.path.join(
            'plugins',
            'imports',
            'tests',
            'test_data',
            'test_prep_update_file_with_csv',
        )
        if not os.path.exists(test_data_path):
            os.mkdir(test_data_path)

        csv_filename = 'can_find_csv.csv'
        path_to_csv = os.path.join(test_data_path, csv_filename)
        with open(path_to_csv, 'w') as fileobj:
            fileobj.write(CSV_DATA_1)

        csv_path, temp_folder_path, errors = utils.prep_update_file(
            path_to_csv
        )

        self.assertEqual(csv_filename, csv_path.split('/')[-1])
