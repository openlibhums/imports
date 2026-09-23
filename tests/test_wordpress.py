"""Tests for the WordPress WXR importer (plugins.imports.wordpress) and its
management command.

They run the command against a small fictional WXR export
(test_data/wordpress_export.xml) with different flag combinations and check
what ends up in the database.
"""

import os
import shutil
from datetime import datetime
from io import StringIO
from unittest import mock

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from cms import models as cms_models
from core import models as core_models
from journal import models as journal_models
from submission import models as submission_models
from utils.testing import helpers

from plugins.imports import wordpress

EXPORT = os.path.join(os.path.dirname(__file__), "test_data", "wordpress_export.xml")
URLOPEN = "plugins.imports.wordpress.importer.urllib.request.urlopen"
# The fixture uses generic category names instead of the EJP ones
TEST_COLLECTIONS = {
    "discourse": ("discourse", "Discourse"),
    "archive": ("archive", "Archive"),
}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def fake_urlopen(pages):
    """Build a urlopen stand-in serving `pages` ({url: bytes}) and failing
    for anything else, so tests never reach the network."""

    def opener(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else request
        if url in pages:
            return FakeResponse(pages[url])
        raise OSError("no fake page for {}".format(url))

    return opener


class WordPressFormattingTests(SimpleTestCase):
    def test_wpautop_paragraphs_and_line_breaks(self):
        html = wordpress.wpautop("One.\n\nTwo.\nStill two.")
        self.assertEqual(html, "<p>One.</p>\n<p>Two.<br />\nStill two.</p>\n")

    def test_wpautop_leaves_block_elements_alone(self):
        html = wordpress.wpautop("<h2>Title</h2>\n\n<ul>\n<li>a</li>\n</ul>")
        self.assertNotIn("<p><h2>", html)
        self.assertNotIn("<p><ul>", html)
        self.assertIn("<h2>Title</h2>", html)

    def test_wptexturize_quotes_dashes_ellipsis(self):
        text = 'He said "no" -- it\'s over... the \'90s <a href="x--y">a "b"</a>'
        self.assertEqual(
            wordpress.wptexturize(text),
            'He said “no” — it’s over… the ’90s <a href="x--y">a “b”</a>',
        )

    def test_wptexturize_skips_code(self):
        text = '<code>a -- "b"</code> c -- "d"'
        self.assertEqual(wordpress.wptexturize(text), '<code>a -- "b"</code> c — “d”')

    def test_fix_mojibake(self):
        self.assertEqual(
            wordpress.fix_mojibake("thisÑthat, andÉ MarxÕs Òso.Ó 1996 Ð now"),
            "this—that, and… Marx’s “so.” 1996 – now",
        )
        for legitimate in ("ESPAÑA", "Órbita", "L’Être", "señor", "École"):
            self.assertEqual(wordpress.fix_mojibake(legitimate), legitimate)

    def test_caption_shortcode(self):
        html = wordpress.format_wp_html(
            '[caption align="alignleft"]<img src="a.jpg" /> A caption[/caption]'
        )
        self.assertEqual(
            html,
            '<figure class="wp-caption alignleft"><img src="a.jpg" />'
            '<figcaption class="wp-caption-text">A caption</figcaption></figure>',
        )

    def test_format_abstract_strips_label(self):
        self.assertEqual(
            wordpress.format_abstract("<strong>Summary:</strong>\n\nText."),
            "<p>Text.</p>",
        )

    def test_parse_release_date(self):
        cases = {
            "2021": (2021, 1, [2021]),
            "Spring-Summer 1995": (1995, 3, [1995]),
            "Fall 1995-Winter 1996": (1995, 9, [1995, 1996]),
            "February 2020 - May 2020": (2020, 2, [2020]),
            "1995-2026": (1995, 1, [1995, 2026]),
        }
        for raw, (year, month, years) in cases.items():
            date, found = wordpress.parse_release_date(raw)
            self.assertEqual((date.year, date.month, found), (year, month, years), raw)
        self.assertEqual(wordpress.parse_release_date("soon"), (None, []))

    def test_parse_block_date(self):
        hint = wordpress.make_aware(datetime(2022, 3, 11))
        cases = {
            "<span>November 12, 2021</span>": (2021, 11, 12),
            "August 22nd, 2021": (2021, 8, 22),
            "9 de febrero, 2022": (2022, 2, 9),
            "Marzo 2022": (2022, 3, 1),
            "11-03-2022": (2022, 3, 11),  # closest reading to the hint
            "22/08/2020": (2020, 8, 22),
        }
        for raw, expected in cases.items():
            date = wordpress.parse_block_date(raw, hint)
            self.assertEqual((date.year, date.month, date.day), expected, raw)
        self.assertIsNone(wordpress.parse_block_date("22-23 febbraio 2022"))

    def test_split_authors(self):
        self.assertEqual(
            wordpress.split_authors("Ada Quill, Bram Voss &amp; Cleo Marsh"),
            ["Ada Quill", "Bram Voss", "Cleo Marsh"],
        )
        self.assertEqual(wordpress.split_authors("***"), [])


@mock.patch.dict(wordpress.COLLECTION_CATEGORIES, TEST_COLLECTIONS, clear=True)
@mock.patch.object(wordpress.consts, "TOP_LEVEL_COLLECTIONS", {"archive"})
class WordPressImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.journal, _ = helpers.create_journals()
        cls.content_type = ContentType.objects.get_for_model(cls.journal)

    def setUp(self):
        patcher = mock.patch(URLOPEN, fake_urlopen({}))
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        for pk in submission_models.Article.objects.filter(
            journal=self.journal
        ).values_list("pk", flat=True):
            shutil.rmtree(
                os.path.join(settings.BASE_DIR, "files", "articles", str(pk)),
                ignore_errors=True,
            )

    def run_import(self, *args, **kwargs):
        out = StringIO()
        call_command(
            "import_wordpress", self.journal.code, EXPORT, *args, stdout=out, **kwargs
        )
        return out.getvalue()

    def article(self, wp_id):
        return submission_models.Article.objects.get(
            journal=self.journal,
            identifier__id_type=wordpress.IDENTIFIER_TYPE,
            identifier__identifier=str(wp_id),
        )

    def articles(self):
        return submission_models.Article.objects.filter(journal=self.journal)

    def galley_html(self, wp_id):
        galley = self.article(wp_id).galley_set.get(type="html")
        with open(galley.file.self_article_path(), encoding="utf-8") as handle:
            return handle.read()

    def sorted_wp_ids(self, issue):
        return [
            article.get_identifier(wordpress.IDENTIFIER_TYPE)
            for article in issue.get_sorted_articles()
        ]

    def nav(self, link_name, parent=None):
        return cms_models.NavigationItem.objects.get(
            content_type=self.content_type,
            object_id=self.journal.pk,
            link_name=link_name,
            top_level_nav=parent,
        )

    # --- flags ---------------------------------------------------------

    def test_dry_run_rolls_back(self):
        output = self.run_import("--dry-run")
        self.assertIn("Dry run", output)
        self.assertIn("articles created: 8", output)
        self.assertFalse(self.articles().exists())
        self.assertFalse(
            journal_models.Issue.objects.filter(journal=self.journal, volume=2).exists()
        )
        self.assertFalse(
            cms_models.Page.objects.filter(object_id=self.journal.pk).exists()
        )

    def test_default_import(self):
        output = self.run_import()

        self.assertIn("articles created: 8", output)
        self.assertIn("articles skipped status: 1", output)
        self.assertIn("errors: 0", output)
        self.assertEqual(self.articles().count(), 8)
        self.assertFalse(
            self.articles().filter(title="Draft Thoughts").exists(),
            "draft posts are skipped without --include-unpublished",
        )

        # authors, keywords, sections
        clocks = self.article(201)
        self.assertEqual(
            [(a.first_name, a.last_name) for a in clocks.frozenauthor_set.all()],
            [("Ada", "Quill"), ("Bram", "Voss")],
        )
        self.assertEqual(self.article(206).frozenauthor_set.count(), 2)
        self.assertEqual(self.article(209).frozenauthor_set.count(), 0)
        self.assertEqual(
            list(clocks.keywords.values_list("word", flat=True)), ["Clocks", "Mirrors"]
        )
        self.assertEqual(
            set(self.articles().values_list("section__name", flat=True)),
            {wordpress.DEFAULT_SECTION},
        )
        self.assertIsNone(clocks.custom_how_to_cite)

    def test_issues(self):
        self.run_import()

        serial = journal_models.Issue.objects.get(
            journal=self.journal, volume=2, issue="1", issue_type__code="issue"
        )
        # release year 2020 matches the post date, so the post date is kept
        self.assertEqual(serial.date.date().isoformat(), "2020-05-15")
        self.assertEqual(serial.order, 0)
        self.assertEqual(
            serial.issue_description,
            "<p>Themed issue on clocks.</p>\n<p>Second paragraph of the description.</p>",
        )
        self.assertEqual(set(self.sorted_wp_ids(serial)), {"201", "202", "203"})

        archive = journal_models.Issue.objects.get(
            journal=self.journal, issue_type__code="archive"
        )
        self.assertEqual((archive.volume, archive.issue), (0, "3"))
        self.assertEqual(archive.issue_title, "Number 3 (Spring-Summer 1999)")
        self.assertEqual(archive.date.date().isoformat(), "1999-03-01")
        self.assertEqual(set(self.sorted_wp_ids(archive)), {"204", "205"})

        discourse = journal_models.Issue.objects.get(
            journal=self.journal, issue_type__code="discourse"
        )
        self.assertEqual(discourse.issue_title, "Round Table on Colours")
        self.assertEqual(discourse.date.date().isoformat(), "2021-03-01")
        self.assertEqual(discourse.issue_description, "<p>Six voices on colour.</p>")

        self.assertIsNone(self.article(208).primary_issue)
        self.assertIsNone(self.article(209).primary_issue)

    def test_article_dates(self):
        self.run_import()
        # from the "Publication Date" block
        self.assertEqual(
            self.article(201).date_published.date().isoformat(), "2020-06-09"
        )
        # WP post date
        self.assertEqual(
            self.article(202).date_published.date().isoformat(), "2020-06-01"
        )
        # front matter added in 2022 to a 1999 issue takes the issue date
        self.assertEqual(
            self.article(204).date_published.date().isoformat(), "1999-03-01"
        )
        self.assertEqual(
            self.article(205).date_published.date().isoformat(), "1999-04-01"
        )

    def test_body_formatting(self):
        self.run_import()

        html = self.galley_html(201)
        self.assertIn(
            "<p>First paragraph with details—which matter — and a “quoted” phrase…</p>",
            html,
        )
        self.assertIn("<p>Second paragraph.<br />\nSame paragraph, new line.</p>", html)
        self.assertIn("<h2>Notes</h2>", html)
        self.assertIn("<p>1. Note one<br />\n2. Note two</p>", html)
        self.assertIn("<h2>Publication Date</h2>", html)
        self.assertNotIn("Boilerplate", html, "text0000 must be ignored")

        clocks = self.article(201)
        self.assertEqual(clocks.abstract, "<p><i>A study of clocks.</i></p>")
        self.assertEqual(clocks.non_specialist_summary, "Clocks — and mirrors")

        colours = self.galley_html(206)
        self.assertIn('<figure class="wp-caption aligncenter"><img src=', colours)
        self.assertIn(
            '<figcaption class="wp-caption-text">A palette</figcaption></figure>',
            colours,
        )
        self.assertIn("<p>Silence follows colour.</p>", colours)

        galley = clocks.galley_set.get(type="html")
        self.assertEqual(galley.file.mime_type, "text/html")

    def test_fallback_ordering(self):
        self.run_import()
        serial = journal_models.Issue.objects.get(
            journal=self.journal, volume=2, issue="1"
        )
        # newest first, with the sub-post grouped after the article it replies to
        self.assertEqual(self.sorted_wp_ids(serial), ["202", "203", "201"])
        archive = journal_models.Issue.objects.get(
            journal=self.journal, issue_type__code="archive"
        )
        # front matter first
        self.assertEqual(self.sorted_wp_ids(archive), ["204", "205"])

    def test_live_order(self):
        pages = {
            "http://example.org/journal/vol-2-no-1/": (
                '<a class="x" href="http://example.org/articles/the-mirror-of-clocks/">The Mirror of Clocks</a>'
                '<a href="http://example.org/articles/editorial-note-a-reply/">Editorial Note: A Reply</a>'
                # permalink changed on the live site: matched by title
                '<a href="http://example.org/articles/editorial-note-renamed/">Editorial Note</a>'
            ).encode("utf-8"),
        }
        with mock.patch(URLOPEN, fake_urlopen(pages)):
            output = self.run_import("--live-order")

        self.assertIn("issues ordered from live site: 1", output)
        serial = journal_models.Issue.objects.get(
            journal=self.journal, volume=2, issue="1"
        )
        self.assertEqual(self.sorted_wp_ids(serial), ["201", "203", "202"])
        # pages that could not be fetched fall back to the default order
        archive = journal_models.Issue.objects.get(
            journal=self.journal, issue_type__code="archive"
        )
        self.assertEqual(self.sorted_wp_ids(archive), ["204", "205"])

    def test_download_pdfs(self):
        pages = {"http://example.org/uploads/rivers.pdf": b"%PDF-1.4 rivers"}
        with mock.patch(URLOPEN, fake_urlopen(pages)):
            output = self.run_import("--download-pdfs")

        self.assertIn("pdf galleys added: 1", output)
        rivers = self.article(205)
        self.assertTrue(rivers.galley_set.filter(type="pdf", label="PDF").exists())
        # the placeholder referenced by the `pdf` meta of 201 is not an
        # upload of that article and is ignored
        self.assertFalse(self.article(201).galley_set.filter(type="pdf").exists())

    def test_download_images(self):
        pages = {"http://example.org/uploads/palette.jpg": b"\xff\xd8 fake jpeg"}
        with mock.patch(URLOPEN, fake_urlopen(pages)):
            output = self.run_import("--download-images")

        self.assertIn("galley images added: 1", output)
        self.assertIn("galley images failed: 0", output)
        galley = self.article(206).galley_set.get(type="html")
        image = galley.images.get()
        self.assertEqual(image.original_filename, "palette.jpg")
        self.assertEqual(image.label, "Image File")
        self.assertFalse(image.is_galley)
        with open(image.self_article_path(), "rb") as handle:
            self.assertEqual(handle.read(), b"\xff\xd8 fake jpeg")
        html = self.galley_html(206)
        self.assertIn('<img src="palette.jpg" alt="" width="300" height="200" />', html)
        self.assertNotIn("example.org/uploads", html)
        self.assertEqual(galley.has_missing_image_files(), [])
        # images hosted elsewhere are left alone
        self.assertIn('src="https://cdn.example.net/badge.png"', self.galley_html(202))

        # a rerun replaces the image instead of piling up copies
        with mock.patch(URLOPEN, fake_urlopen(pages)):
            self.run_import("--download-images")
        article = self.article(206)
        self.assertEqual(article.galley_set.get(type="html").images.count(), 1)
        self.assertEqual(
            core_models.File.objects.filter(
                article_id=article.pk, label="Image File"
            ).count(),
            1,
        )

    def test_images_are_not_downloaded_by_default(self):
        self.run_import()
        html = self.galley_html(206)
        self.assertIn('src="http://example.org/uploads/palette.jpg"', html)
        self.assertFalse(self.article(206).galley_set.get(type="html").images.exists())

    def test_download_images_failure_keeps_remote_src(self):
        output = self.run_import("--download-images")
        self.assertIn("galley images failed: 1", output)
        self.assertIn(
            'src="http://example.org/uploads/palette.jpg"', self.galley_html(206)
        )

    def test_issue_image(self):
        pages = {"http://example.org/uploads/cover.jpg": b"\x89PNG fake"}
        with mock.patch(URLOPEN, fake_urlopen(pages)):
            output = self.run_import()
        self.assertIn("issue images added: 1", output)
        serial = journal_models.Issue.objects.get(
            journal=self.journal, volume=2, issue="1"
        )
        self.assertTrue(serial.large_image)
        serial.large_image.delete()

    def test_pages_and_navigation(self):
        self.run_import()

        pages = cms_models.Page.objects.filter(object_id=self.journal.pk)
        self.assertEqual(
            set(pages.values_list("name", flat=True)),
            {"about", "guidelines", "announcements"},
            "the home page template is skipped",
        )
        about = pages.get(name="about")
        self.assertFalse(about.is_markdown)
        self.assertIn("<h2>About the Journal</h2>", about.content)
        self.assertIn(
            "<p>We publish imaginary studies.</p>\n<p>Since 1999.</p>", about.content
        )
        self.assertIn(
            '<div class="contact"><p><strong>Ada Quill</strong></p>', about.content
        )
        self.assertIn(
            '<h3><a href="/site/guidelines/">Guidelines</a></h3>', about.content
        )
        self.assertEqual(
            pages.get(name="announcements").content, "<p>News from the journal.</p>"
        )

        about_nav = self.nav("About")
        self.assertTrue(about_nav.has_sub_nav)
        self.assertEqual(
            [
                (item.link_name, item.link)
                for item in about_nav.sub_nav_items().order_by("sequence")
            ],
            [("Guidelines", "/site/guidelines/"), ("About", "/site/about/")],
        )
        self.assertEqual(self.nav("Announcements").link, "/site/announcements/")
        collections = self.nav(wordpress.COLLECTIONS_NAV_NAME)
        self.assertEqual(
            self.nav("Discourse", parent=collections).link, "/collections/discourse"
        )
        self.assertEqual(self.nav("Archive").link, "/collections/archive")

    def test_skip_pages(self):
        self.run_import("--skip-pages")
        self.assertFalse(
            cms_models.Page.objects.filter(object_id=self.journal.pk).exists()
        )
        self.assertFalse(
            cms_models.NavigationItem.objects.filter(
                object_id=self.journal.pk, link_name="About"
            ).exists()
        )

    def test_include_unpublished(self):
        self.run_import("--include-unpublished")
        draft = self.articles().get(title="Draft Thoughts")
        self.assertEqual(draft.stage, submission_models.STAGE_UNSUBMITTED)
        self.assertIsNone(draft.date_published)
        self.assertEqual(self.articles().count(), 9)

    def test_exclude_by_category_lineage(self):
        output = self.run_import("--exclude", "In Latin")
        self.assertIn("articles skipped excluded: 1", output)
        self.assertFalse(self.articles().filter(title="De Coloribus").exists())
        self.assertEqual(self.articles().count(), 7)

    def test_only_by_parent_title_and_article_id(self):
        output = self.run_import("--only", "Vol. 2, No. 1", "--only", "205")
        self.assertEqual(
            set(self.articles().values_list("title", flat=True)),
            {
                "The Mirror of Clocks",
                "Editorial Note",
                "Editorial Note: A Reply",
                "On Fictional Rivers",
            },
        )
        self.assertIn("articles skipped not selected: 4", output)
        self.assertNotIn("did not match", output)

    def test_unmatched_filter_token_warns(self):
        output = self.run_import("--exclude", "nonexistent-token")
        self.assertIn("filter token 'nonexistent-token' did not match", output)

    def test_rerun_is_idempotent(self):
        self.run_import()
        first = {
            "articles": self.articles().count(),
            "issues": journal_models.Issue.objects.filter(journal=self.journal).count(),
            "pages": cms_models.Page.objects.filter(object_id=self.journal.pk).count(),
            "nav": cms_models.NavigationItem.objects.filter(
                object_id=self.journal.pk
            ).count(),
        }
        output = self.run_import()
        self.assertIn("articles created: 0", output)
        self.assertIn("articles updated: 8", output)
        self.assertEqual(
            first,
            {
                "articles": self.articles().count(),
                "issues": journal_models.Issue.objects.filter(
                    journal=self.journal
                ).count(),
                "pages": cms_models.Page.objects.filter(
                    object_id=self.journal.pk
                ).count(),
                "nav": cms_models.NavigationItem.objects.filter(
                    object_id=self.journal.pk
                ).count(),
            },
        )
        # galleys are replaced, not duplicated
        self.assertEqual(self.article(201).galley_set.count(), 1)
        self.assertEqual(
            core_models.File.objects.filter(article_id=self.article(201).pk).count(), 1
        )
        self.assertEqual(self.article(201).frozenauthor_set.count(), 2)
        serial = journal_models.Issue.objects.get(
            journal=self.journal, volume=2, issue="1"
        )
        self.assertEqual(self.sorted_wp_ids(serial), ["202", "203", "201"])
