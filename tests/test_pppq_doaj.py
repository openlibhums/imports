import contextlib
import io
import os
import tempfile

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from identifiers import models as identifiers_models
from journal import models as journal_models
from submission import models as submission_models
from utils.testing import helpers

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def write_public_file(files_root, ojs_id, filename, content):
    """Create <files_root>/articles/<ojs_id>/public/<filename> with content."""
    public_dir = os.path.join(files_root, "articles", str(ojs_id), "public")
    os.makedirs(public_dir, exist_ok=True)
    with open(os.path.join(public_dir, filename), "wb") as open_file:
        open_file.write(content)


def build_record(title, ojs_id, volume="30", issue="1/2", doi=None,
                 authors=None, pages=True, full_text_url=True):
    """Return a single DOAJ <record> XML fragment.

    ``pages`` and ``full_text_url`` can be set False to omit those elements so
    the quirk-handling paths can be exercised.
    """
    doi_line = "<doi>%s</doi>" % doi if doi else ""
    author_lines = ""
    for name, email in authors or []:
        email_line = "<email>%s</email>" % email if email else ""
        author_lines += (
            "<author><name>%s</name>%s</author>" % (name, email_line)
        )
    page_lines = "<startPage>8</startPage><endPage>13</endPage>" if pages else ""
    url_line = (
        '<fullTextUrl format="html">'
        "http://example.org/PPPQ/article/view/%s</fullTextUrl>" % ojs_id
        if full_text_url else ""
    )
    return """
    <record>
        <language>eng</language>
        <publicationDate>2010-04-01</publicationDate>
        <volume>{volume}</volume>
        <issue>{issue}</issue>
        {page_lines}
        {doi_line}
        <publisherRecordId>{ojs_id}</publisherRecordId>
        <title language="eng">{title}</title>
        <authors>{author_lines}</authors>
        <abstract language="eng">An abstract.</abstract>
        {url_line}
        <keywords/>
    </record>
    """.format(
        volume=volume, issue=issue, page_lines=page_lines, doi_line=doi_line,
        ojs_id=ojs_id, title=title, author_lines=author_lines,
        url_line=url_line,
    )


def write_xml(path, records):
    with open(path, "w", encoding="utf-8") as open_file:
        open_file.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n<records>%s</records>'
            % "".join(records)
        )


class PPPQDOAJImportTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.press = helpers.create_press()
        cls.journal, cls.journal_two = helpers.create_journals()
        cls.owner = helpers.create_user("pppq-owner@example.org")
        cls.owner.is_active = True
        cls.owner.save()

        cls.temp_dir = tempfile.mkdtemp(prefix="pppq-doaj-test")
        cls.files_root = os.path.join(cls.temp_dir, "ojs_files")

        # 100: normal article with DOI, one author, real PDF galley
        write_public_file(cls.files_root, 100, "100-PB.pdf", PDF_BYTES)
        # 200: a .txt file that is actually a PDF
        write_public_file(cls.files_root, 200, "200-PB.txt", PDF_BYTES)
        # 300: full issue PDF (own issue: vol 31 / issue 3)
        write_public_file(cls.files_root, 300, "300-full.pdf", PDF_BYTES)
        # 400 front cover, 500 back cover
        write_public_file(cls.files_root, 400, "400-front.pdf", PDF_BYTES)
        write_public_file(cls.files_root, 500, "500-back.pdf", PDF_BYTES)
        # 600: article with no public file at all -> gap
        # 900: dry-run only record, PDF present but never imported in setup
        write_public_file(cls.files_root, 900, "900-PB.pdf", PDF_BYTES)

        records = [
            build_record(
                "The Conscience of a Prosecutor", 100,
                doi="10.13021/G8pppq.302010.100",
                authors=[("David Luban", "luban@law.georgetown.edu")],
            ),
            build_record("An Article With a Text PDF", 200),
            build_record(
                "Full Issue, Spring 2010", 300, volume="31", issue="3",
            ),
            build_record("Front Cover", 400),
            build_record("Back Cover", 500),
            build_record("An Article With No Files", 600),
        ]
        cls.xml_path = os.path.join(cls.temp_dir, "doaj.xml")
        write_xml(cls.xml_path, records)

        # 950: full-issue record for dry-run coverage (PDF present on disk)
        write_public_file(cls.files_root, 950, "950-full.pdf", PDF_BYTES)
        cls.dry_run_xml_path = os.path.join(cls.temp_dir, "doaj_dry.xml")
        write_xml(
            cls.dry_run_xml_path,
            [
                build_record("A Dry Run Article", 900),
                build_record(
                    "Full Issue, Dry Run", 950, volume="99", issue="9",
                ),
            ],
        )

        # Quirk records: missing pages, single-token and three-token author
        # names, and an empty volume.
        cls.quirks_xml_path = os.path.join(cls.temp_dir, "doaj_quirks.xml")
        write_xml(
            cls.quirks_xml_path,
            [
                build_record(
                    "A Pageless Article", 700, pages=False,
                    authors=[("Cher", None)],
                ),
                build_record(
                    "A Three Token Author Article", 750,
                    authors=[("Mary Anne Evans", "mae@example.org")],
                ),
                build_record("A Volumeless Article", 800, volume=""),
            ],
        )

        # A record with no fullTextUrl cannot yield an OJS id.
        cls.no_url_xml_path = os.path.join(cls.temp_dir, "doaj_no_url.xml")
        write_xml(
            cls.no_url_xml_path,
            [build_record("A URL-less Article", 999, full_text_url=False)],
        )

        call_command(
            "import_pppq_doaj",
            cls.xml_path,
            cls.files_root,
            cls.journal.code,
            "--owner-id", str(cls.owner.pk),
        )

    def article_for_ojs_id(self, ojs_id):
        return identifiers_models.Identifier.objects.get(
            id_type="pppq_ojs_id",
            identifier=str(ojs_id),
            article__journal=self.journal,
        ).article

    def test_normal_article_is_created_with_metadata(self):
        article = self.article_for_ojs_id(100)
        self.assertEqual(article.title, "The Conscience of a Prosecutor")
        self.assertEqual(article.stage, submission_models.STAGE_PUBLISHED)
        self.assertTrue(article.is_import)
        self.assertEqual(article.owner, self.owner)
        self.assertIsNotNone(article.date_published)
        self.assertEqual(article.first_page, 8)
        self.assertEqual(article.last_page, 13)

    def test_normal_article_has_issue_author_doi_and_galley(self):
        article = self.article_for_ojs_id(100)

        self.assertIsNotNone(article.primary_issue)
        self.assertEqual(article.primary_issue.volume, 30)
        self.assertEqual(article.primary_issue.issue, "1/2")
        self.assertIn(article, article.primary_issue.articles.all())

        frozen = submission_models.FrozenAuthor.objects.filter(article=article)
        self.assertEqual(frozen.count(), 1)
        author = frozen.first()
        self.assertEqual(author.first_name, "David")
        self.assertEqual(author.last_name, "Luban")
        self.assertEqual(author.frozen_email, "luban@law.georgetown.edu")

        self.assertTrue(
            identifiers_models.Identifier.objects.filter(
                id_type="doi",
                identifier="10.13021/G8pppq.302010.100",
                article=article,
            ).exists()
        )
        self.assertEqual(article.galley_set.count(), 1)

    def test_section_is_article(self):
        article = self.article_for_ojs_id(100)
        self.assertEqual(article.section.name, "Article")

    def test_txt_file_is_saved_as_pdf_galley(self):
        article = self.article_for_ojs_id(200)
        self.assertEqual(article.galley_set.count(), 1)
        galley = article.galley_set.first()
        self.assertTrue(
            galley.file.original_filename.lower().endswith(".pdf"),
            galley.file.original_filename,
        )
        self.assertEqual(galley.file.mime_type, "application/pdf")

    def test_full_issue_creates_issue_galley_and_no_article(self):
        self.assertFalse(
            identifiers_models.Identifier.objects.filter(
                id_type="pppq_ojs_id",
                identifier="300",
                article__journal=self.journal,
            ).exists()
        )
        issue = journal_models.Issue.objects.get(
            journal=self.journal, volume=31, issue="3",
        )
        self.assertTrue(
            journal_models.IssueGalley.objects.filter(issue=issue).exists()
        )

    def test_front_and_back_cover_sections(self):
        front = self.article_for_ojs_id(400)
        back = self.article_for_ojs_id(500)
        self.assertEqual(front.section.name, "Front Cover")
        self.assertEqual(back.section.name, "Back Cover")

    def test_article_without_file_is_reported_as_gap(self):
        article = self.article_for_ojs_id(600)
        self.assertEqual(article.galley_set.count(), 0)

    def test_reimport_does_not_duplicate_article_galley(self):
        article = self.article_for_ojs_id(100)
        before_galleys = article.galley_set.count()
        self.assertEqual(before_galleys, 1)
        call_command(
            "import_pppq_doaj",
            self.xml_path,
            self.files_root,
            self.journal.code,
            "--owner-id", str(self.owner.pk),
        )
        self.assertEqual(
            self.article_for_ojs_id(100).galley_set.count(),
            before_galleys,
        )

    def test_reimport_is_idempotent(self):
        before = submission_models.Article.objects.filter(
            journal=self.journal,
        ).count()
        call_command(
            "import_pppq_doaj",
            self.xml_path,
            self.files_root,
            self.journal.code,
            "--owner-id", str(self.owner.pk),
        )
        after = submission_models.Article.objects.filter(
            journal=self.journal,
        ).count()
        self.assertEqual(before, after)
        self.assertEqual(
            identifiers_models.Identifier.objects.filter(
                id_type="pppq_ojs_id",
                identifier="100",
                article__journal=self.journal,
            ).count(),
            1,
        )
        self.assertEqual(
            submission_models.FrozenAuthor.objects.filter(
                article=self.article_for_ojs_id(100),
            ).count(),
            1,
        )

    def test_dry_run_persists_nothing(self):
        articles_dir = os.path.join(settings.BASE_DIR, "files", "articles")
        issues_dir = os.path.join(settings.BASE_DIR, "files", "issues")

        def snapshot(directory):
            return sorted(os.listdir(directory)) if os.path.isdir(directory) \
                else []

        articles_before = snapshot(articles_dir)
        issues_before = snapshot(issues_dir)
        article_count_before = submission_models.Article.objects.count()
        issue_galley_count_before = journal_models.IssueGalley.objects.count()

        call_command(
            "import_pppq_doaj",
            self.dry_run_xml_path,
            self.files_root,
            self.journal.code,
            "--owner-id", str(self.owner.pk),
            "--dry-run",
        )

        # No article or issue-galley rows persisted (article 900, full issue 950)
        self.assertFalse(
            identifiers_models.Identifier.objects.filter(
                id_type="pppq_ojs_id",
                identifier="900",
                article__journal=self.journal,
            ).exists()
        )
        self.assertEqual(
            submission_models.Article.objects.count(),
            article_count_before,
        )
        self.assertEqual(
            journal_models.IssueGalley.objects.count(),
            issue_galley_count_before,
        )
        self.assertFalse(
            journal_models.Issue.objects.filter(
                journal=self.journal, volume=99, issue="9",
            ).exists()
        )

        # No files written to disk for either the article or the issue galley
        self.assertEqual(snapshot(articles_dir), articles_before)
        self.assertEqual(snapshot(issues_dir), issues_before)

    def test_missing_pages_do_not_crash_and_leave_pages_blank(self):
        call_command(
            "import_pppq_doaj",
            self.quirks_xml_path,
            self.files_root,
            self.journal.code,
            "--owner-id", str(self.owner.pk),
        )
        article = self.article_for_ojs_id(700)
        self.assertIsNone(article.first_page)
        self.assertIsNone(article.last_page)

    def test_single_token_author_name_split(self):
        call_command(
            "import_pppq_doaj",
            self.quirks_xml_path,
            self.files_root,
            self.journal.code,
            "--owner-id", str(self.owner.pk),
        )
        author = submission_models.FrozenAuthor.objects.get(
            article=self.article_for_ojs_id(700),
        )
        self.assertEqual(author.first_name, "")
        self.assertEqual(author.last_name, "Cher")

    def test_three_token_author_name_split(self):
        call_command(
            "import_pppq_doaj",
            self.quirks_xml_path,
            self.files_root,
            self.journal.code,
            "--owner-id", str(self.owner.pk),
        )
        author = submission_models.FrozenAuthor.objects.get(
            article=self.article_for_ojs_id(750),
        )
        self.assertEqual(author.first_name, "Mary Anne")
        self.assertEqual(author.last_name, "Evans")

    def test_empty_volume_is_handled(self):
        call_command(
            "import_pppq_doaj",
            self.quirks_xml_path,
            self.files_root,
            self.journal.code,
            "--owner-id", str(self.owner.pk),
        )
        article = self.article_for_ojs_id(800)
        self.assertIsNotNone(article.primary_issue)
        self.assertEqual(article.primary_issue.volume, 0)

    def test_missing_full_text_url_is_recorded_not_crashed(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            call_command(
                "import_pppq_doaj",
                self.no_url_xml_path,
                self.files_root,
                self.journal.code,
                "--owner-id", str(self.owner.pk),
            )
        summary = output.getvalue()
        self.assertIn("Records skipped: 1", summary)
        self.assertEqual(
            submission_models.Article.objects.filter(
                title="A URL-less Article",
            ).count(),
            0,
        )
