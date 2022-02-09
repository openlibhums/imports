from django.test import TestCase

from plugins.imports import utils, export, views, plugin_settings
from core import models as core_models, logic as core_logic
from submission import models as submission_models
from journal import models as journal_models
from utils.testing import helpers
from utils.shared import clear_cache
from nose.tools import set_trace

from datetime import datetime
from django.utils.timezone import make_aware, utc
from rest_framework import routers
from django.http import HttpRequest
import csv
import io
import re
import zipfile
import os

CSV_DATA_1 = """Article title,Article abstract,Keywords,Licence,Language,Author salutation,Author given name,Author middle name,Author surname,Author email,Author ORCID,Author institution,Author department,Author biography,Author is primary (Y/N),Author is corporate (Y/N),Article ID,DOI,DOI (URL form),Date accepted,Date published,Page numbers,Competing interests,Article section,Stage,File import identifier,Journal code,Journal title,ISSN,Volume number,Issue number,Issue title,Issue pub date
Variopleistocene Inquilibriums,How it all went down.,"dinosaurs, Socratic teaching",CC BY-NC-SA 4.0,English,Prof,Unreal,J.,Person3,unrealperson3@example.com,https://orcid.org/0000-1234-5578-901X,University of Michigan Medical School,Cancer Center,Prof Unreal J. Person3 teaches dinosaurs but they are employed in a hospital.,Y,N,,10.1234/tst.1,https://doi.org/10.1234/tst.1,2021-10-24T10:24:00+00:00,2021-10-25T10:25:25+00:00,9–43,The author reports no competing interests.,Article,Editor Copyediting,,TST,Journal One,0000-0000,1,1,Fall 2021,2021-09-15T09:15:15+00:00
,,,,,,Unreal,J.,Person5,unrealperson5@example.com,,University of Calgary,Anthropology,Unreal J. Person5 is the author of <i>Being</i>.,N,N,,,,,,,,,,,,,,,,,
,,,,,,Unreal,J.,Person6,unrealperson6@example.com,,University of Mars,Crater Nine,Does Unreal J. Person6 exist?,N,N,,,,,,,,,,,,,,,,,
"""



# Utils


def run_import(csv_string_or_dict, mock_request, path_to_zip=None):
    """
    Simulates the import
    """

    if isinstance(csv_string_or_dict, str):
        csv_string = csv_string_or_dict
    elif isinstance(csv_string_or_dict, dict):
        csv_string = string_from_csv_dict(csv_string_or_dict)

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


def read_saved_article_data(article, structure='string'):
    """
    Gets saved article data from the database for comparison
    with the expected article data
    """
    row_i = 1
    csv_dict = {}
    csv_dict[row_i] = dict.fromkeys(plugin_settings.UPDATE_CSV_HEADERS, '')

    article_fields = {
        'Article title': article.title if article.title else '',
        'Article abstract': article.abstract if article.abstract else '',
        'Keywords': ", ".join([str(kw) for kw in article.keywords.all()]),
        'Licence': str(article.license) if article.license else '',
        'Language': article.get_language_display() if article.language else '',
        #  author columns will go here
        'Article ID': str(article.id),
        'DOI': article.get_doi() if article.get_doi() else '',
        'DOI (URL form)': 'https://doi.org/' + article.get_doi(
            ) if article.get_doi() else '',
        'Date accepted': article.date_accepted.isoformat() if article.date_accepted else '',
        'Date published': article.date_published.isoformat() if article.date_published else '',
        'Page numbers': article.page_numbers if article.page_numbers else '',
        'Competing interests': article.competing_interests if article.competing_interests else '',
        'Article section': article.section.name if article.section else '',
        'Stage': article.stage if article.stage else '',
        'File import identifier': str(article.pk),
        # read_saved_files needs updating
        # 'File import identifier': read_saved_files(article),
        'Journal code': article.journal.code,
        'Journal title': article.journal.name,
        'ISSN': article.journal.issn,
        'Volume number': str(article.issue.volume) if article.issue else '',
        'Issue number': str(article.issue.issue) if article.issue else '',
        'Issue title': article.issue.issue_title if article.issue else '',
        'Issue pub date': article.issue.date.isoformat() if article.issue else '',
    }

    csv_dict[row_i].update(article_fields)

    author_rows = {}
    for frozen_author in article.frozenauthor_set.all():
        order = frozen_author.order
        author_rows[order] = read_saved_frozen_author_data(
            frozen_author,
            article
        )

    if author_rows:
        for order in sorted(list(author_rows.keys())):
            if row_i not in csv_dict:
                csv_dict[row_i] = dict.fromkeys(plugin_settings.UPDATE_CSV_HEADERS, '')
            csv_dict[row_i].update(author_rows[order])
            row_i += 1

    if structure == 'dict':
        return csv_dict

    elif structure == 'string':
        return string_from_csv_dict(csv_dict)

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
        'Author salutation': frozen_author.author.salutation if frozen_author.author else '',
        'Author given name': frozen_author.first_name if frozen_author.first_name else '',
        'Author middle name': frozen_author.middle_name if frozen_author.middle_name else '',
        'Author surname': frozen_author.last_name if frozen_author.last_name else '',
        'Author email': frozen_author.author.email if frozen_author.author else '',
        'Author ORCID': 'https://orcid.org/' + frozen_author.frozen_orcid if (
            frozen_author.frozen_orcid
        ) else '',
        'Author institution': frozen_author.institution if frozen_author.institution else '',
        'Author department': frozen_author.department if frozen_author.department else '',
        'Author biography': frozen_author.frozen_biography if frozen_author.frozen_biography else '',
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


def dict_from_csv_string(csv_string):
    reader = csv.DictReader(csv_string.splitlines(), restval='')
    return_dict = {}
    i = 0
    for row in reader:
        i += 1
        return_dict[i] = row
    return return_dict

def string_from_csv_dict(
        csv_dict,
        fieldnames = CSV_DATA_1.splitlines()[0].split(',')
    ):
    with io.StringIO() as mock_csv_file:

        dialect = csv.excel()
        dialect.lineterminator = '\n'
        dialect.quoting = csv.QUOTE_MINIMAL

        writer = csv.DictWriter(
            mock_csv_file,
            fieldnames=fieldnames,
            dialect=dialect,
        )

        writer.writeheader()
        for row_i in sorted(list(csv_dict.keys())):
            writer.writerow(csv_dict[row_i])

        csv_string = mock_csv_file.getvalue()
        return csv_string


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

        cls.journal_one, cls.journal_two = helpers.create_journals()
        cls.journal_one.workflow()
        issue_type = journal_models.IssueType.objects.get_or_create(
            journal=cls.journal_one,
            code='issue'
        )
        cls.mock_request = HttpRequest()
        cls.test_user = helpers.create_user(username='unrealperson12@example.com')
        cls.mock_request.user = cls.test_user
        cls.mock_request.journal = cls.journal_one
        for plugin_element_name in ['Typesetting Plugin']:
            element = core_logic.handle_element_post(
                cls.journal_one.workflow(),
                plugin_element_name,
                cls.mock_request,
            )
            cls.journal_one.workflow().elements.add(element)
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

    def test_headings_match_plugin_settings_headers(self):
        # Uncomment to get new metadata_template.csv
        # print('\n\nCopy and paste to docs/source/_static/metadata_template.csv:')
        # print('\n\n'+CSV_DATA_1.splitlines()[0]+'\n\n')

        expected_headers = set(CSV_DATA_1.splitlines()[0].split(','))
        settings_headers = set(plugin_settings.UPDATE_CSV_HEADERS)
        self.assertEqual(expected_headers, settings_headers)

    def test_update_article_metadata_fresh_import(self):
        """
        Whether the attributes of the article were
        saved correctly on first import.
        """

        self.maxDiff = None
        csv_data_2 = dict_from_csv_string(CSV_DATA_1)

        # Uncomment to get new sample_import.csv
        # print('\n\nCopy and paste to docs/source/_static/sample_import.csv:')
        # print('\n\n'+string_from_csv_dict(csv_data_2)+'\n\n')

        # add article id to expected data
        csv_data_2[1]['Article ID'] = '1'
        csv_data_2[1]['File import identifier'] = '1'

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1, structure='dict')

        self.assertEqual(csv_data_2, saved_article_data)

    def test_update_article_metadata_update(self):
        self.maxDiff = None

        clear_cache()

        # change changeable article data
        csv_data_3 = dict_from_csv_string(CSV_DATA_1)
        csv_data_3[1]['Article title'] = 'Multipleistocene Exquilibriums'
        csv_data_3[1]['Article abstract'] = 'How it is still going down.'
        csv_data_3[1]['Keywords'] = 'better dinosaurs, worse teaching'
        csv_data_3[1]['Licence'] = 'CC BY 4.0'
        csv_data_3[1]['Language'] = 'French'
        csv_data_3[1]['Author salutation'] = 'Prof'
        csv_data_3[1]['Author given name'] = 'Unreal'
        csv_data_3[1]['Author middle name'] = 'J.'
        csv_data_3[1]['Author surname'] = 'Person3'
        csv_data_3[1]['Author email'] = 'unrealperson3@example.com'
        csv_data_3[1]['Author ORCID'] = 'https://orcid.org/0000-1234-5578-901X'
        csv_data_3[1]['Author institution'] = 'University of Michigan Medical School'
        csv_data_3[1]['Author department'] = 'Cancer Center'
        csv_data_3[1]['Author biography'] = 'Prof Unreal J. Person3 teaches dinosaurs '\
                                            'and so they are employed in a hospital.'
        csv_data_3[1]['Author is primary (Y/N)'] = 'Y'
        csv_data_3[1]['Author is corporate (Y/N)'] = 'N'
        csv_data_3[1]['Article ID'] = '1'
        # csv_data_3[1]['DOI'] = 
        # csv_data_3[1]['DOI (URL form)'] = 
        csv_data_3[1]['Date accepted'] = '2021-10-25T10:25:25+00:00'
        csv_data_3[1]['Date published'] = '2021-10-26T10:26:00+00:00'
        csv_data_3[1]['Page numbers'] = 'iii-ix'
        csv_data_3[1]['Competing interests'] = 'The author is unfortunately on the payroll ' \
                                               'of Rex from Toy Story.'
        # csv_data_3[1]['Article section'] = 
        # csv_data_3[1]['Stage'] = 
        csv_data_3[1]['File import identifier'] = '1'
        # csv_data_3[1]['Journal code'] = 
        # csv_data_3[1]['Journal title'] = 
        # csv_data_3[1]['ISSN'] = 
        # csv_data_3[1]['Volume number'] = 
        # csv_data_3[1]['Issue number'] = 
        # csv_data_3[1]['Issue title'] = 
        # csv_data_3[1]['Issue pub date'] = 

        run_import(csv_data_3, self.mock_request)

        # Uncomment to get new sample_update.csv
        # print('\n\nCopy and paste to docs/source/_static/sample_update.csv:')
        # print('\n\n'+string_from_csv_dict(csv_data_3)+'\n\n')

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1, structure='dict')
        self.assertEqual(csv_data_3, saved_article_data)

    def test_empty_fields(self):
        """
        Tests whether Janeway accepts null values for nonrequired fields
        """
        self.maxDiff = None
        clear_cache()

        csv_data_12 = dict_from_csv_string(CSV_DATA_1)

        # blank out non-required rows
        # csv_data_12[1]['Article title'] = 'Multipleistocene Exquilibriums'
        csv_data_12[1]['Article abstract'] = ''
        csv_data_12[1]['Keywords'] = ''
        csv_data_12[1]['Licence'] = ''
        csv_data_12[1]['Language'] = ''
        csv_data_12[1]['Author salutation'] = ''
        csv_data_12[1]['Author given name'] = ''
        csv_data_12[1]['Author middle name'] = ''
        csv_data_12[1]['Author surname'] = ''
        csv_data_12[1]['Author email'] = ''
        csv_data_12[1]['Author ORCID'] = ''
        csv_data_12[1]['Author institution'] = ''
        csv_data_12[1]['Author department'] = ''
        csv_data_12[1]['Author biography'] = ''
        csv_data_12[1]['Author is primary (Y/N)'] = ''
        csv_data_12[1]['Author is corporate (Y/N)'] = ''
        csv_data_12[1]['Article ID'] = ''
        csv_data_12[1]['DOI'] = ''
        csv_data_12[1]['DOI (URL form)'] = ''
        csv_data_12[1]['Date accepted'] = ''
        csv_data_12[1]['Date published'] = ''
        csv_data_12[1]['Page numbers'] = ''
        csv_data_12[1]['Competing interests'] = ''
        # csv_data_12[1]['Article section'] = 'Article'
        csv_data_12[1]['Stage'] = ''
        csv_data_12[1]['File import identifier'] = ''
        # csv_data_12[1]['Journal code'] = 'TST'
        # csv_data_12[1]['Journal title'] = 'Journal One'
        csv_data_12[1]['ISSN'] = ''
        csv_data_12[1]['Volume number'] = ''
        csv_data_12[1]['Issue number'] = ''
        csv_data_12[1]['Issue title'] = ''
        # csv_data_12[1]['Issue pub date'] = '2021-09-15T09:15:15+00:00'


        # add article id and a few other sticky things back to expected data
        csv_data_12[1]['Article ID'] = '2'
        csv_data_12[1]['Stage'] = 'Unassigned'
        csv_data_12[1]['File import identifier'] = '2'
        csv_data_12[1]['ISSN'] = '0000-0000'
        csv_data_12[1]['Volume number'] = '0'
        csv_data_12[1]['Issue number'] = '0'

        # remove second and third rows (authors)
        csv_data_12.pop(2)
        csv_data_12.pop(3)

        run_import(csv_data_12, self.mock_request)
        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2, structure='dict')

        # account for uuid4-generated email address
        for i in [1]:
            saved_article_data[i]['Author email'] = ''

        self.assertEqual(csv_data_12, saved_article_data)

    def test_update_with_empty(self):
        """
        Tests whether Janeway properly interprets blank fields on update
        """
        self.maxDiff = None
        clear_cache()

        csv_data_13 = dict_from_csv_string(CSV_DATA_1)

        # blank out non-required rows to test whether blanks are written during update
        # csv_data_13[1]['Article title'] = 'Multipleistocene Exquilibriums'
        csv_data_13[1]['Article abstract'] = ''
        csv_data_13[1]['Keywords'] = ''
        csv_data_13[1]['Licence'] = ''
        csv_data_13[1]['Language'] = ''
        csv_data_13[1]['Author salutation'] = ''
        csv_data_13[1]['Author given name'] = ''
        csv_data_13[1]['Author middle name'] = ''
        csv_data_13[1]['Author surname'] = ''
        csv_data_13[1]['Author email'] = ''
        csv_data_13[1]['Author ORCID'] = ''
        csv_data_13[1]['Author institution'] = ''
        csv_data_13[1]['Author department'] = ''
        csv_data_13[1]['Author biography'] = ''
        csv_data_13[1]['Author is primary (Y/N)'] = ''
        csv_data_13[1]['Author is corporate (Y/N)'] = ''
        csv_data_13[1]['Article ID'] = '1' # update article ID in expected data
        csv_data_13[1]['DOI'] = ''
        csv_data_13[1]['DOI (URL form)'] = ''
        csv_data_13[1]['Date accepted'] = ''
        csv_data_13[1]['Date published'] = ''
        csv_data_13[1]['Page numbers'] = ''
        csv_data_13[1]['Competing interests'] = ''
        # csv_data_13[1]['Article section'] = 'Article'
        # csv_data_13[1]['Stage'] = 'Editor Copyediting'
        csv_data_13[1]['File import identifier'] = '1' # update article ID in expected data
        # csv_data_13[1]['Journal code'] = 'TST'
        # csv_data_13[1]['Journal title'] = 'Journal One'
        csv_data_13[1]['ISSN'] = ''
        # csv_data_13[1]['Volume number'] = '1'
        # csv_data_13[1]['Issue number'] = '1'
        csv_data_13[1]['Issue title'] = ''
        # csv_data_13[1]['Issue pub date'] = '2021-09-15T09:15:15+00:00'

        # remove second and third rows (authors)
        csv_data_13.pop(2)
        csv_data_13.pop(3)

        run_import(csv_data_13, self.mock_request)

        # account for blanks in import data that aren't written to db
        csv_data_13[1]['DOI'] = '10.1234/tst.1'
        csv_data_13[1]['DOI (URL form)'] = 'https://doi.org/10.1234/tst.1'
        csv_data_13[1]['ISSN'] = '0000-0000'

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1, structure='dict')

        self.assertEqual(csv_data_13, saved_article_data)

    def test_prepare_reader_rows(self):
        self.maxDiff = None

        csv_data_8 = dict_from_csv_string(CSV_DATA_1)

        # add article id to test update
        csv_data_8[1]['Article ID'] = '1'

        reader = csv.DictReader(string_from_csv_dict(csv_data_8).splitlines())
        article_groups = utils.prepare_reader_rows(reader)

        reader_rows = [r for r in csv.DictReader(
            string_from_csv_dict(csv_data_8).splitlines()
        )]

        expected_article_groups = [{
            'type': 'Update',
            'primary_row': reader_rows[0],
            'author_rows': [reader_rows[1], reader_rows[2]],
            'primary_row_number': 0,
            'article_id': '1',
        }]
        self.assertEqual(expected_article_groups, article_groups)

    def test_prep_update(self):
        self.maxDiff = None
        csv_data_16 = dict_from_csv_string(CSV_DATA_1)

        # add article id to test update
        csv_data_16[1]['Article ID'] = '1'

        reader = csv.DictReader(string_from_csv_dict(csv_data_16).splitlines())
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
        self.maxDiff = None

        clear_cache()

        article_1 = submission_models.Article.objects.get(id=1)

        keywords = ['better dinosaurs', 'worse teaching']
        utils.update_keywords(keywords, article_1)
        saved_keywords = [str(w) for w in article_1.keywords.all()]
        self.assertEqual(keywords, saved_keywords)

    def test_user_becomes_owner(self):
        self.maxDiff = None

        clear_cache()

        article_1 = submission_models.Article.objects.get(id=1)
        self.assertEqual(self.mock_request.user.email, article_1.owner.email)

    def test_changes_to_issue(self):
        self.maxDiff = None

        clear_cache()

        csv_data_11 = dict_from_csv_string(CSV_DATA_1)

        # change issue title and date
        csv_data_11[1]['Issue title'] = 'Winter 2022'
        csv_data_11[1]['Issue pub date'] = '2022-01-15T01:15:15+00:00'

        run_import(csv_data_11, self.mock_request)

        # change article id
        csv_data_11[1]['Article ID'] = '2'
        csv_data_11[1]['File import identifier'] = '2'

        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2, structure='dict')

        self.assertEqual(csv_data_11, saved_article_data)

    def test_changes_to_author_fields(self):
        self.maxDiff = None

        clear_cache()
        csv_data_4 = dict_from_csv_string(CSV_DATA_1)

        # change data for unrealperson3@example.com

        # csv_data_4[1]['Author salutation'] = 'Prof'
        csv_data_4[1]['Author given name'] = 'Surreal'
        csv_data_4[1]['Author middle name'] = 'H.'
        csv_data_4[1]['Author surname'] = 'Personne3'
        # csv_data_4[1]['Author email'] = 'unrealperson3@example.com'
        csv_data_4[1]['Author ORCID'] = 'https://orcid.org/0000-1234-5678-909X'
        csv_data_4[1]['Author institution'] = 'University of Toronto'
        csv_data_4[1]['Author department'] = 'Children\'s Center'
        csv_data_4[1]['Author biography'] = 'Many are the accomplishments '\
                                            'of Surreal Personne3'
        csv_data_4[1]['Author is primary (Y/N)'] = ''
        csv_data_4[1]['Author is corporate (Y/N)'] = 'N'

        # remove unrealperson5@example.com
        csv_data_4[2] = csv_data_4.pop(3)

        # add article id
        csv_data_4[1]['Article ID'] = '1'
        csv_data_4[1]['File import identifier'] = '1'

        # add primary N to expected data
        csv_data_4[1]['Author is primary (Y/N)'] = 'N'

        run_import(csv_data_4, self.mock_request)

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1, structure='dict')

        self.assertEqual(csv_data_4, saved_article_data)

    def test_update_frozen_author(self):
        self.maxDiff = None

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
        self.maxDiff = None
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
        self.maxDiff = None

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
        self.maxDiff = None

        clear_cache()

        csv_data_5 = dict_from_csv_string(CSV_DATA_1)

        # change section
        csv_data_5[1]['Article section'] = 'Interview'

        # add article id
        csv_data_5[1]['Article ID'] = '1'
        csv_data_5[1]['File import identifier'] = '1'

        run_import(csv_data_5, self.mock_request)

        article_1 = submission_models.Article.objects.get(id=1)
        saved_article_data = read_saved_article_data(article_1, structure='dict')
        self.assertEqual(csv_data_5, saved_article_data)

    def test_different_stages(self):
        self.maxDiff = None

        stages = [
            'Unassigned',
            'Editor Copyediting',
            'typesetting_plugin',
            'pre_publication',
            'Published',
        ]

        saved_stages = []

        for stage_name in stages:

            clear_cache()

            csv_data_6 = dict_from_csv_string(CSV_DATA_1)

            # import "new" article with different stage
            csv_data_6[1]['Stage'] = stage_name

            run_import(csv_data_6, self.mock_request)
            article = submission_models.Article.objects.all().order_by('-id')[0]

            # add article id
            csv_data_6[1]['Article ID'] = str(article.pk)
            csv_data_6[1]['File import identifier'] = str(article.pk)

            saved_article_data = read_saved_article_data(article, structure='dict')
            saved_stages.append(saved_article_data[1]['Stage'])

        self.assertEqual(stages, saved_stages)

    def test_bad_data(self):
        self.maxDiff = None

        clear_cache()


        csv_data_7 = dict_from_csv_string(CSV_DATA_1)
        csv_data_7[1]['Article title'] = 'Title£$^^£&&££&££££$'
        csv_data_7[1]['Article abstract'] = 'Abstract;;;;;;'
        csv_data_7[1]['Keywords'] = 'Keywords2f, a09srh14!$'
        csv_data_7[1]['Licence'] = 'License£%^^£&'
        # csv_data_7[1]['Language'] = 'fra'
        csv_data_7[1]['Author salutation'] = 'salutation$*^%*^%*&'
        csv_data_7[1]['Author given name'] = 'Author given name 2f0SD)F*'
        csv_data_7[1]['Author middle name'] = 'Author middle name %^&*%^&*'
        csv_data_7[1]['Author surname'] = 'Author surname %^*%&*'
        csv_data_7[1]['Author email'] = 'Author email %^&*%^UY'
        csv_data_7[1]['Author ORCID'] = 'https://orcid.org/n0ns3ns3'
        csv_data_7[1]['Author institution'] = 'Author institution$^&*^%&(^%())'
        csv_data_7[1]['Author department'] = 'Author department 2043230'
        csv_data_7[1]['Author biography'] = 'se0f9asef)(FAE)(SH'
        # csv_data_7[1]['Author is primary (Y/N)'] = 'Y'
        csv_data_7[1]['Author is corporate (Y/N)'] = 'gobbeldy'
        csv_data_7[1]['Article ID'] = ''
        csv_data_7[1]['DOI'] = ''
        csv_data_7[1]['DOI (URL form)'] = ''
        csv_data_7[1]['Date accepted'] = ''
        csv_data_7[1]['Date published'] = ''
        csv_data_7[1]['Article section'] = 'Section $%^&$%^&$%*'
        csv_data_7[1]['Stage'] = 'Editor Copyediting'
        csv_data_7[1]['File import identifier'] = ''
        # csv_data_7[1]['Journal code'] = 'TST'
        # csv_data_7[1]['Journal title'] = 'Journal One'
        # csv_data_7[1]['ISSN'] = '0000-0000'
        # csv_data_7[1]['Volume number'] = 1
        # csv_data_7[1]['Issue number'] = 1
        csv_data_7[1]['Issue title'] = 'Issue name 20432%^&RIY$%*RI'
        # csv_data_7[1]['Issue pub date'] = '2021-09-15T09:15:15+00:00'


        # Note: Not all of the above should not be importable,
        # esp. the email and orcid
        run_import(csv_data_7, self.mock_request)

        # add article id
        csv_data_7[1]['Article ID'] = '2'
        csv_data_7[1]['File import identifier'] = '2'

        # account for human-legible N for non corresondence author
        csv_data_7[1]['Author is corporate (Y/N)'] = 'N'

        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2, structure='dict')
        self.assertEqual(csv_data_7, saved_article_data)

    def test_data_with_whitespace(self):
        self.maxDiff = None

        clear_cache()

        csv_data_9 = dict_from_csv_string(CSV_DATA_1)
        for k in csv_data_9[1].keys():
            some_whitespace = '             '
            csv_data_9[1][k] = some_whitespace+csv_data_9[1][k]+some_whitespace

        run_import(csv_data_9, self.mock_request)

        # add article id
        csv_data_10 = dict_from_csv_string(CSV_DATA_1)
        csv_data_10[1]['Article ID'] = '2'
        csv_data_10[1]['File import identifier'] = '2'

        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2, structure='dict')
        self.assertEqual(csv_data_10, saved_article_data)

    def test_corporate_author_import(self):
        self.maxDiff = None
        clear_cache()

        csv_data_14 = dict_from_csv_string(CSV_DATA_1)
        csv_data_14[1]['Author salutation'] = ''
        csv_data_14[1]['Author given name'] = ''
        csv_data_14[1]['Author middle name'] = ''
        csv_data_14[1]['Author surname'] = ''
        csv_data_14[1]['Author email'] = ''
        csv_data_14[1]['Author ORCID'] = ''
        csv_data_14[1]['Author institution'] = 'University of Michigan Dinosaur Institute'
        csv_data_14[1]['Author department'] = ''
        csv_data_14[1]['Author biography'] = ''
        csv_data_14[1]['Author is primary (Y/N)'] = 'N'
        csv_data_14[1]['Author is corporate (Y/N)'] = 'Y'

        run_import(csv_data_14, self.mock_request)

        csv_data_14[1]['Article ID'] = '2'
        csv_data_14[1]['File import identifier'] = '2'

        article_2 = submission_models.Article.objects.get(id=2)
        saved_article_data = read_saved_article_data(article_2, structure='dict')
        self.assertEqual(csv_data_14, saved_article_data)

#    Needs updating after new file import is written
#    def test_handle_file_import(self):
#        self.maxDiff = None
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

    def test_verify_headers(self):
        csv_string = 'Inadequate,Headers\n' \
                     'data, other data'
        path_to_csv = os.path.join('plugins','imports','tests','test_data',
                                   'test_verify_headers.csv')
        with open(path_to_csv, 'w') as fileobj:
            fileobj.write(csv_string)
        errors = []
        errors = utils.verify_headers(path_to_csv, errors)
        self.assertTrue(
            'Expected headers not found' in errors[0]['error']
        )

    def test_validate_selected_char_fields(self):
        csv_string = 'Article title,Stage,Language\n' \
                     'title,Bad stage 1,zzz\n' \
                     'title,Bad stage 2,Dinosaur\n'
        path_to_csv = os.path.join('plugins','imports','tests','test_data',
                                   'test_validate_selected_char_fields.csv')
        with open(path_to_csv, 'w') as fileobj:
            fileobj.write(csv_string)
        errors = []
        journal = self.journal_one
        errors = utils.validate_selected_char_fields(path_to_csv, errors, journal)
        error_messages = ".".join([msg['error'] for msg in errors])
        self.assertTrue(
            ('Unrecognized data in field Stage' in error_messages and
             'Unrecognized data in field Language' in error_messages)
        )

    def test_language_codes(self):

        csv_data_17 = dict_from_csv_string(CSV_DATA_1)
        saved_languages = []
        expected_languages = [
            ('hun','Hungarian'),
            ('yor','Yoruba')
        ]

        csv_data_17[1]['Language'] = expected_languages[0][0]
        run_import(csv_data_17, self.mock_request)
        article = submission_models.Article.objects.all().order_by('-id')[0]
        saved_languages.append((article.language, article.get_language_display()))

        csv_data_17[1]['Language'] = expected_languages[1][1]
        run_import(csv_data_17, self.mock_request)
        article = submission_models.Article.objects.all().order_by('-id')[0]
        saved_languages.append((article.language, article.get_language_display()))

        self.assertEqual(expected_languages, saved_languages)
