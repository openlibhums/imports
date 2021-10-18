"""
Test cases for utils in imports plugin

Run with
python manage.py test --keepdb imports.tests.test_utils

"""
from django.test import TestCase

from plugins.imports import utils
from submission import models as submission_models
from journal import models as journal_models
from utils.testing import helpers

from django.http import HttpRequest
import csv


class TestUtils(TestCase):
    @classmethod
    def setUpTestData(cls):
        print("""setUpTestData: Run once to set up non-modified data
            for all class methods.""")
        journal_one, journal_two = helpers.create_journals()
        issue_type = journal_models.IssueType.objects.get_or_create(
            journal=journal_one,
            code='issue'
        )

    def setUp(self):
        print("setUp: Run once for every test method to setup clean data.")

    def testUpdateArticleMetadata(self):

        request = HttpRequest()
        reader = csv.DictReader(CSV_DATA_1.splitlines())
        zip_folder_path = "test_zip_1.zip"

        errors, actions = utils.update_article_metadata(
            request,
            reader,
            zip_folder_path,
        )

        article_1 = submission_models.Article.objects.get(id=1)

        self.assertEqual(article_1.id, 1)
        self.assertEqual(
            article_1.title,
            ('Pimping: valuable teaching tool or mistreatment?  '
             'Perceptions of medical students and faculty differ.'),
        )

        saved_keywords = ",".join([
            str(kw) for kw in article_1.keywords.all()
        ])
        expected_keywords = ('medical education,Socratic teaching,pimping,'
                             ' wellness,clinical education')
        self.assertEqual(saved_keywords, expected_keywords)
        self.assertEqual(str(article_1.license), 'CC BY-NC-SA 4.0')
        self.assertEqual(article_1.language, 'English')
        saved_author_one = article_1.authors.all()[0]

        expected_author_one = 'Unreal Person3'

        self.assertEqual(saved_author_one, expected_author_one)
        print(saved_author_one)

        print(article_1.get_identifier('doi'))
        print(article_1.date_accepted)
        print(article_1.date_published)
        print(article_1.section)
        print(article_1.stage)
        print(article_1.journal)
        print(article_1.owner)
        print(article_1.issue)

        # self.assertEqual()


        from nose.tools import set_trace; set_trace()



CSV_DATA_1 = """Article title,Keywords,License,Language,Author Salutation,Author surname,Author given name,Author email,Author institution,Author is primary (Y/N),Author ORCID,Article ID,DOI,DOI (URL form),Date accepted,Date published,Article section,Stage,Article filename,Article sequence,Journal Code,Journal title,ISSN,Volume number,Issue number,Issue name,Issue pub date
Pimping: valuable teaching tool or mistreatment?  Perceptions of medical students and faculty differ.,"medical education,Socratic teaching,pimping, wellness,clinical education",CC BY-NC-SA 4.0,English,,Person3,Unreal,unreal3@example.com,University of Michigan Medical School,Y,https://orcid.org/0000-1234-5678-9012,10,,,,2021-08-31,Article,Editor Copyediting,,4,TST,Journal One,0000-0000,1,1,,2021-08-31 13:58:59+00:00
"Prescription Stimulant-Induced Neurotoxicity: Mechanisms, outcomes, and relevance to ADHD","attention deficit disorder with hyperactivity,prefrontal cortex,amphetamine,central nervous system stimulants,students,young adults,prescription drug misuse",CC BY-NC-SA 4.0,English,,Person4,Unreal,unreal4@example.com,"University of Michigan School of Public Health, Department of Environmental Health Sciences",Y,https://orcid.org/0000-2345-6789-0123,11,,,,2021-08-31,Article,Editor Copyediting,,6,TST,Journal One,0000-0000,1,1,,2021-08-31 13:58:59+00:00"""
