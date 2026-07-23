"""Import articles from a WordPress WXR export into Janeway.

Usage:

    python manage.py import_wordpress <journal_code> <path_to_export.xml>
    python manage.py import_wordpress ejp ejp.WordPress.xml --dry-run
    python manage.py import_wordpress ejp ejp.WordPress.xml \
        --exclude in-italian --exclude "Featured Books"
    python manage.py import_wordpress ejp ejp.WordPress.xml --only 3712
"""

import html
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from cms import models as cms_models
from core import files as core_files
from core import models as core_models
from identifiers import models as identifier_models
from journal import models as journal_models
from submission import models as submission_models

NS = {
    "wp": "http://wordpress.org/export/1.2/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "excerpt": "http://wordpress.org/export/1.2/excerpt/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

ARTICLE_POST_TYPE = "articles"
IDENTIFIER_TYPE = "wordpressid"
ISSUE_TITLE_RE = re.compile(r"^Vol\.?\s*(\d+)\s*,?\s*No\.?\s*(\d+)$", re.I)
INVALID_XML_CHARS_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
# Author strings are free text: "A, B", "A & B", "A and B", "A with B"
AUTHOR_SPLIT_RE = re.compile(r"\s*(?:,|&|\band\b|\bwith\b)\s*")

DEFAULT_SECTION = "Article"
# Language buckets, not real sections
NON_SECTION_CATEGORIES = {"in-italian", "in-spanish"}

# Top-level WP categories imported as collections, mapped to
# (issue type code, issue type name). Articles under any other category
# are attached to regular issues via their post_add parent.
# TODO: These are specific to EJP,think of how to provide these from CLI instead
COLLECTION_CATEGORIES = {
    "discourse": ("discourse", "Discourse"),
    "symposia": ("symposia", "Symposia"),
    "features": ("features", "Features"),
    "articles": ("articles", "Articles"),
}
COLLECTIONS_NAV_NAME = "Collections"


class DryRunRollback(Exception):
    pass


def element_text(item, tag):
    el = item.find(tag, NS)
    return (el.text or "") if el is not None else ""


def collect_postmeta(item):
    """Return {meta_key: first non-empty value} for an item."""
    meta = {}
    for pm in item.findall("wp:postmeta", NS):
        key = element_text(pm, "wp:meta_key")
        value = element_text(pm, "wp:meta_value")
        if key and (key not in meta or not meta[key]):
            meta[key] = value
    return meta


def parse_date(meta_date):
    """Parse a WP '2021-10-10 11:36:17' date into an aware datetime."""
    if not meta_date or meta_date.startswith("0000"):
        return None
    try:
        parsed = datetime.strptime(meta_date, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return timezone.make_aware(parsed, timezone.get_current_timezone())


def split_authors(raw):
    """Split a free-text author string into individual names."""
    raw = re.sub(r"\s+", " ", html.unescape(raw or "")).strip()
    if not raw or set(raw) <= {"*"}:
        return []
    names = []
    for part in AUTHOR_SPLIT_RE.split(raw):
        part = part.strip(" .;")
        if part:
            names.append(part)
    return names


def parse_person_name(name):
    """Best-effort split of 'First [Middles] Last' into name parts."""
    tokens = name.split()
    if len(tokens) == 1:
        return "", "", tokens[0]
    first, last = tokens[0], tokens[-1]
    middle = " ".join(tokens[1:-1])
    return first, middle, last


def build_body_html(meta):
    """Assemble the article body from the text and blocks_* postmeta."""
    parts = []
    for key in ("text", "text0000"):
        if meta.get(key):
            parts.append(meta[key])
    index = 0
    while True:
        text = meta.get("blocks_{}_text".format(index))
        title = meta.get("blocks_{}_title".format(index))
        if text is None and title is None:
            break
        if title:
            parts.append("<h2>{}</h2>".format(title))
        if text:
            parts.append(text)
        index += 1
    return "\n".join(parts).strip()


def collect_keywords(meta):
    keywords = []
    index = 0
    while True:
        word = meta.get("topics_{}_text".format(index))
        if word is None:
            break
        word = word.strip()
        if word:
            keywords.append(word[:200])
        index += 1
    return keywords


def category_slugs(item):
    return [
        cat.get("nicename")
        for cat in item.findall("category")
        if cat.get("domain") == "category" and cat.get("nicename")
    ]


def category_names(item):
    return [
        (cat.get("nicename"), (cat.text or "").strip())
        for cat in item.findall("category")
        if cat.get("domain") == "category" and cat.get("nicename")
    ]


class WordPressImporter:
    def __init__(self, journal, xml_path, options, stdout):
        self.journal = journal
        self.xml_path = xml_path
        self.options = options
        self.stdout = stdout
        self.category_parents = {}
        self.category_labels = {}  # slug -> human-readable name
        self.issue_posts = {}  # wp post_id -> post item
        self.attachments = {}  # wp post_id -> attachment URL
        self.issue_cache = {}  # wp post_id -> journal.Issue
        self.exclude_tokens = self.clean_tokens(options.get("exclude"))
        self.only_tokens = self.clean_tokens(options.get("only"))
        self.matched_tokens = set()
        self.stats = {
            "articles_created": 0,
            "articles_updated": 0,
            "articles_skipped_status": 0,
            "articles_skipped_excluded": 0,
            "articles_skipped_not_selected": 0,
            "issues_linked": 0,
            "issue_images_added": 0,
            "authors_created": 0,
            "errors": 0,
        }

    @staticmethod
    def clean_tokens(tokens):
        return {token.strip().lower() for token in tokens or [] if token.strip()}

    def log(self, message):
        self.stdout.write(message)

    def load(self):
        with open(self.xml_path, encoding="utf-8") as handle:
            raw = handle.read()
        raw = INVALID_XML_CHARS_RE.sub("", raw)
        root = ET.fromstring(raw)
        channel = root.find("channel")

        for cat in channel.findall("wp:category", NS):
            slug = element_text(cat, "wp:category_nicename")
            parent = element_text(cat, "wp:category_parent")
            if slug:
                self.category_parents[slug] = parent or None
                self.category_labels[slug] = element_text(cat, "wp:cat_name").strip()

        items = channel.findall("item")
        articles = []
        for item in items:
            post_type = element_text(item, "wp:post_type")
            post_id = element_text(item, "wp:post_id")
            if post_type == ARTICLE_POST_TYPE:
                articles.append(item)
            elif post_type == "post":
                self.issue_posts[post_id] = item
            elif post_type == "attachment":
                url = element_text(item, "wp:attachment_url")
                if url:
                    self.attachments[post_id] = url
        return articles

    def category_lineage(self, slug):
        seen = []
        while slug and slug not in seen:
            seen.append(slug)
            slug = self.category_parents.get(slug)
        return seen

    def pick_section(self, item):
        for slug, name in category_names(item):
            if slug not in NON_SECTION_CATEGORIES and name:
                return name[:200]
        return DEFAULT_SECTION

    def collection_category(self, item):
        """Return the (code, name) of the item's collection category, if any."""
        for slug in category_slugs(item):
            root = self.category_lineage(slug)[-1]
            if root in COLLECTION_CATEGORIES:
                return COLLECTION_CATEGORIES[root]
        return None

    def get_issue_type(self, code, pretty_name):
        issue_type, _ = journal_models.IssueType.objects.get_or_create(
            journal=self.journal,
            code=code,
            defaults={
                "pretty_name": pretty_name,
                # some names are already plural ("Symposia", "Features")
                "custom_plural": pretty_name,
            },
        )
        return issue_type

    def collection_issue(self, title, bucket, issue_date=None):
        issue, created = journal_models.Issue.objects.get_or_create(
            journal=self.journal,
            issue_title=title[:300],
            issue_type=self.get_issue_type(*bucket),
            defaults={"volume": 1, "issue": ""},
        )
        if created and issue_date:
            issue.date = issue_date
            issue.save()
        return issue

    def attach_issue_image(self, issue, meta):
        """Download the parent post's featured image into Issue.large_image.

        The hero image of each WP issue/collection page is its featured
        image (`_thumbnail_id` postmeta -> attachment post -> URL). Skipped
        when the issue already has one, so reruns do not re-download.
        """
        if self.options["dry_run"] or issue.large_image:
            return
        url = self.attachments.get((meta.get("_thumbnail_id") or "").strip())
        if not url:
            return
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                image_bytes = response.read()
        except Exception as exc:
            self.log("  ! could not download issue image {}: {}".format(url, exc))
            return
        name = os.path.basename(url.split("?")[0]) or "issue-image"
        issue.large_image.save(name, ContentFile(image_bytes), save=True)
        self.stats["issue_images_added"] += 1
        self.log("  * issue image for '{}' <- {}".format(issue.display_title, name))

    def issue_for_post(self, post_id, bucket=None):
        if post_id in self.issue_cache:
            return self.issue_cache[post_id]
        item = self.issue_posts.get(post_id)
        if item is None:
            return None

        title = element_text(item, "title").strip()
        if not title:
            return None
        meta = collect_postmeta(item)

        issue_date = None
        release_year = (meta.get("release_date") or "").strip()
        if re.fullmatch(r"\d{4}", release_year):
            issue_date = timezone.make_aware(
                datetime(int(release_year), 1, 1),
                timezone.get_current_timezone(),
            )
        if issue_date is None:
            issue_date = parse_date(element_text(item, "wp:post_date"))

        serial_match = ISSUE_TITLE_RE.match(title)
        if serial_match:
            volume, number = serial_match.groups()
            issue, created = journal_models.Issue.objects.get_or_create(
                journal=self.journal,
                volume=int(volume),
                issue=number,
                issue_type=self.get_issue_type("issue", "Issue"),
            )
            if created and issue_date:
                issue.date = issue_date
                issue.save()
        elif bucket:
            issue = self.collection_issue(title, bucket, issue_date)
        else:
            issue, created = journal_models.Issue.objects.get_or_create(
                journal=self.journal,
                issue_title=title[:300],
                issue_type=self.get_issue_type("collection", "Collection"),
                defaults={"volume": 1, "issue": ""},
            )
            if created and issue_date:
                issue.date = issue_date
                issue.save()

        description = (meta.get("description") or "").strip()
        if description and issue.issue_description != description:
            issue.issue_description = description
            issue.save()

        self.attach_issue_image(issue, meta)
        self.issue_cache[post_id] = issue
        return issue

    def match_keys(self, item, meta):
        """All the case-insensitive tokens an article can be selected by.

        Covers the article's own WordPress post id, every category slug and
        name in its lineage, and its parent (post_add) post's id, slug and
        title, so --exclude/--only accept whichever form is most readable.
        """
        keys = {element_text(item, "wp:post_id")}
        for slug in category_slugs(item):
            for ancestor in self.category_lineage(slug):
                keys.add(ancestor.lower())
                label = self.category_labels.get(ancestor)
                if label:
                    keys.add(label.lower())
        parent_id = (meta.get("post_add") or "").strip()
        parent = self.issue_posts.get(parent_id)
        if parent is not None:
            keys.add(parent_id)
            keys.add(element_text(parent, "wp:post_name").strip().lower())
            keys.add(element_text(parent, "title").strip().lower())
        keys.discard("")
        return keys

    def filtered_out(self, item, meta):
        """Apply --only and --exclude. Returns True if the article should
        be skipped, updating the relevant stats."""
        keys = self.match_keys(item, meta)
        if self.only_tokens:
            hits = self.only_tokens & keys
            if not hits:
                self.stats["articles_skipped_not_selected"] += 1
                return True
            self.matched_tokens |= hits
        hits = self.exclude_tokens & keys
        if hits:
            self.matched_tokens |= hits
            self.stats["articles_skipped_excluded"] += 1
            return True
        return False

    def existing_article(self, wp_id):
        identifier = identifier_models.Identifier.objects.filter(
            id_type=IDENTIFIER_TYPE,
            identifier=wp_id,
            article__journal=self.journal,
        ).first()
        return identifier.article if identifier else None

    def create_frozen_authors(self, article, meta):
        article.frozenauthor_set.all().delete()
        for order, name in enumerate(split_authors(meta.get("author")), start=1):
            first, middle, last = parse_person_name(name)
            submission_models.FrozenAuthor.objects.create(
                article=article,
                first_name=first,
                middle_name=middle,
                last_name=last,
                order=order,
            )
            self.stats["authors_created"] += 1

    def attach_keywords(self, article, meta):
        submission_models.KeywordArticle.objects.filter(article=article).delete()
        for order, word in enumerate(collect_keywords(meta), start=1):
            keyword, _ = submission_models.Keyword.objects.get_or_create(word=word)
            submission_models.KeywordArticle.objects.get_or_create(
                article=article,
                keyword=keyword,
                defaults={"order": order},
            )

    def attach_galleys(self, article, meta):
        for galley in core_models.Galley.objects.filter(article=article):
            galley_file = galley.file
            galley.delete()
            if galley_file:
                galley_file.delete()  # also unlinks the file on disk

        body = build_body_html(meta)
        if body:
            content = ContentFile(
                body.encode("utf-8"),
                name="{}.html".format(slugify(article.title)[:60] or "article"),
            )
            saved_file = core_files.save_file_to_article(
                content,
                article,
                owner=None,
                label="HTML",
                is_galley=True,
            )
            saved_file.mime_type = "text/html"
            saved_file.save()
            core_models.Galley.objects.create(
                article=article,
                file=saved_file,
                label="HTML",
                type="html",
            )

        pdf_url = self.attachments.get((meta.get("pdf") or "").strip())
        if pdf_url and self.options["download_pdfs"]:
            try:
                with urllib.request.urlopen(pdf_url, timeout=30) as response:
                    pdf_bytes = response.read()
            except Exception as exc:
                self.log("  ! could not download {}: {}".format(pdf_url, exc))
                return
            content = ContentFile(
                pdf_bytes, name=os.path.basename(pdf_url) or "article.pdf"
            )
            saved_file = core_files.save_file_to_article(
                content,
                article,
                owner=None,
                label="PDF",
                is_galley=True,
            )
            core_models.Galley.objects.create(
                article=article,
                file=saved_file,
                label="PDF",
                type="pdf",
            )

    def import_article(self, item):
        wp_id = element_text(item, "wp:post_id")
        status = element_text(item, "wp:status")
        title = html.unescape(element_text(item, "title")).strip()
        meta = collect_postmeta(item)

        if self.filtered_out(item, meta):
            return
        if status != "publish" and not self.options["include_unpublished"]:
            self.stats["articles_skipped_status"] += 1
            return
        if not title:
            title = "Untitled (WordPress post {})".format(wp_id)
        published = status == "publish"
        date_published = parse_date(
            element_text(item, "wp:post_date_gmt")
        ) or parse_date(element_text(item, "wp:post_date"))

        abstract = (meta.get("intro") or "").strip()
        abstract = re.sub(
            r"^\s*<h\d[^>]*>\s*Abstract:?\s*</h\d>\s*", "", abstract, flags=re.I
        )

        section, _ = submission_models.Section.objects.get_or_create(
            journal=self.journal,
            name=self.pick_section(item),
        )

        article = self.existing_article(wp_id)
        created = article is None
        if created:
            article = submission_models.Article(
                journal=self.journal,
                is_import=True,
            )

        article.title = title[:999]
        article.abstract = abstract or None
        article.section = section
        article.stage = (
            submission_models.STAGE_PUBLISHED
            if published
            else submission_models.STAGE_UNSUBMITTED
        )
        article.date_published = date_published if published else None
        article.date_submitted = date_published

        if meta.get("citation_text") and meta.get("hide_citation") != "1":
            article.custom_how_to_cite = meta["citation_text"].strip()
        else:
            article.custom_how_to_cite = None

        summary = (meta.get("short_description") or "").strip()
        article.non_specialist_summary = summary or None
        article.save()

        if created:
            identifier_models.Identifier.objects.create(
                id_type=IDENTIFIER_TYPE,
                identifier=wp_id,
                article=article,
            )

        self.create_frozen_authors(article, meta)
        self.attach_keywords(article, meta)
        # galley file writes cannot be rolled back, so dry runs skip them
        if not self.options["dry_run"]:
            self.attach_galleys(article, meta)

        bucket = self.collection_category(item)
        issue = self.issue_for_post((meta.get("post_add") or "").strip(), bucket)
        if issue is None and bucket:
            # catch-all collection for posts with no parent post
            issue = self.collection_issue(bucket[1], bucket)
        if issue:
            issue.articles.add(article)
            article.primary_issue = issue
            article.save()
            self.stats["issues_linked"] += 1

        self.stats["articles_created" if created else "articles_updated"] += 1
        self.log(
            "  {} [{}] {} ({} authors{})".format(
                "+" if created else "~",
                wp_id,
                title[:70],
                article.frozenauthor_set.count(),
                ", issue: {}".format(issue) if issue else "",
            )
        )

    def create_collection_navigation(self):
        """Create a navbar entry with a sub-item per collection issue type.

        Follows the same link convention as
        cms.NavigationItem.toggle_collection_nav. Issue types without
        issues (e.g. after an --exclude run) get no sub-item.
        """
        content_type = ContentType.objects.get_for_model(self.journal)
        top_nav, _ = cms_models.NavigationItem.objects.get_or_create(
            content_type=content_type,
            object_id=self.journal.pk,
            link_name=COLLECTIONS_NAV_NAME,
            defaults={"has_sub_nav": True},
        )
        active_items = 0
        for sequence, (code, name) in enumerate(COLLECTION_CATEGORIES.values()):
            sub_items = cms_models.NavigationItem.objects.filter(
                content_type=content_type,
                object_id=self.journal.pk,
                link_name=name,
                top_level_nav=top_nav,
            )
            if journal_models.Issue.objects.filter(
                journal=self.journal, issue_type__code=code
            ).exists():
                active_items += 1
                if not sub_items.exists():
                    cms_models.NavigationItem.objects.create(
                        content_type=content_type,
                        object_id=self.journal.pk,
                        link_name=name,
                        top_level_nav=top_nav,
                        link="/collections/{}".format(code),
                        sequence=sequence,
                    )
            else:
                sub_items.delete()
        if not active_items:
            top_nav.delete()

    def run(self):
        articles = self.load()
        self.log(
            "Found {} '{}' items ({} issue candidate posts, {} attachments)".format(
                len(articles),
                ARTICLE_POST_TYPE,
                len(self.issue_posts),
                len(self.attachments),
            )
        )
        for item in articles:
            try:
                with transaction.atomic():
                    self.import_article(item)
            except Exception as exc:
                self.stats["errors"] += 1
                self.log(
                    "  ! error importing WP post {}: {}".format(
                        element_text(item, "wp:post_id"), exc
                    )
                )
        self.create_collection_navigation()
        for token in sorted(
            (self.exclude_tokens | self.only_tokens) - self.matched_tokens
        ):
            self.log(
                "  ! warning: filter token '{}' did not match any article".format(token)
            )
        return self.stats


class Command(BaseCommand):
    help = "Import articles, issues and authors from a WordPress WXR export."

    def add_arguments(self, parser):
        parser.add_argument(
            "journal_code", help="Code of the target journal (e.g. ejp)"
        )
        parser.add_argument("xml_path", help="Path to the WordPress export XML file")
        parser.add_argument(
            "--exclude",
            action="append",
            default=[],
            metavar="TOKEN",
            help="Skip articles matching TOKEN (repeatable, case-insensitive)."
            " A token can be a category slug or name (e.g. 'in-italian',"
            " 'In Italian'), a collection/issue parent post's WordPress id,"
            " slug or title (e.g. 'Featured Books'), or an article's"
            " WordPress id.",
        )
        parser.add_argument(
            "--only",
            action="append",
            default=[],
            metavar="TOKEN",
            help="Import only articles matching TOKEN (repeatable). Accepts"
            " the same tokens as --exclude, e.g. a single collection title"
            " or a single article's WordPress id. --exclude still applies"
            " on top.",
        )
        parser.add_argument(
            "--include-unpublished",
            action="store_true",
            help="Also import draft/private posts (as unsubmitted articles)",
        )
        parser.add_argument(
            "--download-pdfs",
            action="store_true",
            help="Download PDF attachments from the live site and attach them"
            " as galleys",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report what would be imported, then roll everything"
            " back. Galley files and issue images are neither written nor"
            " deleted.",
        )

    def handle(self, *args, **options):
        try:
            journal = journal_models.Journal.objects.get(code=options["journal_code"])
        except journal_models.Journal.DoesNotExist:
            raise CommandError(
                "No journal with code '{}' found.".format(options["journal_code"])
            )
        if not os.path.isfile(options["xml_path"]):
            raise CommandError("Export file not found: {}".format(options["xml_path"]))

        importer = WordPressImporter(journal, options["xml_path"], options, self.stdout)
        try:
            with transaction.atomic():
                stats = importer.run()
                if options["dry_run"]:
                    raise DryRunRollback()
        except DryRunRollback:
            stats = importer.stats
            self.stdout.write("\nDry run: all database changes rolled back.")

        self.stdout.write("\nSummary:")
        for key, value in sorted(stats.items()):
            self.stdout.write("  {}: {}".format(key.replace("_", " "), value))
