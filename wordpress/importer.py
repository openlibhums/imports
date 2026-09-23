"""The WordPress WXR importer: articles, issues, collections, pages and
navigation of a Janeway journal from an export file."""

import html
import os
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.text import slugify

from cms import models as cms_models
from core import files as core_files
from core import models as core_models
from identifiers import models as identifier_models
from journal import models as journal_models
from submission import models as submission_models
from utils.logger import get_logger

from . import consts
from .text import (
    fix_mojibake,
    format_abstract,
    format_wp_html,
    strip_tags,
    wptexturize,
)
from .wxr import (
    build_body_html,
    category_slugs,
    collect_keywords,
    collect_postmeta,
    element_text,
    fallback_order,
    link_key,
    normalise_title,
    parse_block_date,
    parse_date,
    parse_person_name,
    parse_release_date,
    split_authors,
)

logger = get_logger(__name__)


class DryRunRollback(Exception):
    pass


class WordPressImporter:
    def __init__(
        self,
        journal,
        xml_path,
        stdout=None,
        dry_run=False,
        include_unpublished=False,
        download_pdfs=False,
        download_images=False,
        live_order=False,
        skip_pages=False,
        exclude=None,
        only=None,
    ):
        self.journal = journal
        self.xml_path = xml_path
        self.stdout = stdout
        self.dry_run = dry_run
        self.include_unpublished = include_unpublished
        self.download_pdfs = download_pdfs
        self.download_images = download_images
        self.live_order = live_order
        self.skip_pages = skip_pages
        self.site_url = ""
        self.category_parents = {}
        self.category_labels = {}  # slug -> human-readable name
        self.issue_posts = {}  # wp post_id -> post item
        self.article_items = {}  # wp post_id -> article item (all statuses)
        self.article_by_link = {}  # permalink path -> wp post_id
        self.page_items = []  # published WP pages
        self.menu_items = []  # nav_menu_item posts
        self.attachments = {}  # wp post_id -> attachment URL
        self.attachment_parents = {}  # wp post_id -> parent post id
        self.attachments_by_parent = {}  # parent post id -> [(id, url)]
        self.issue_cache = {}  # wp post_id -> journal.Issue
        self.issue_max_year = {}  # issue pk -> last year of its release date
        self.touched_issues = {}  # issue pk -> (issue, parent post item or None)
        self.live_order_cache = {}  # parent post URL -> [permalink paths]
        self.image_cache = {}  # image URL -> bytes, or None when it failed
        self.imported_pages = {}  # wp page id -> cms.Page
        self.exclude_tokens = self.clean_tokens(exclude)
        self.only_tokens = self.clean_tokens(only)
        self.matched_tokens = set()
        self.stats = {
            "articles_created": 0,
            "articles_updated": 0,
            "articles_skipped_status": 0,
            "articles_skipped_excluded": 0,
            "articles_skipped_not_selected": 0,
            "issues_linked": 0,
            "issues_ordered": 0,
            "issues_ordered_from_live_site": 0,
            "issue_images_added": 0,
            "authors_created": 0,
            "pdf_galleys_added": 0,
            "galley_images_added": 0,
            "galley_images_failed": 0,
            "pages_imported": 0,
            "errors": 0,
        }

    @staticmethod
    def clean_tokens(tokens):
        return {token.strip().lower() for token in tokens or [] if token.strip()}

    def log(self, message):
        if self.stdout is not None:
            self.stdout.write(message)
        else:
            logger.info(message)

    def load(self):
        with open(self.xml_path, encoding="utf-8") as handle:
            raw = handle.read()
        raw = consts.INVALID_XML_CHARS_RE.sub("", raw)
        root = ET.fromstring(raw)
        channel = root.find("channel")
        self.site_url = (
            element_text(channel, "wp:base_site_url") or element_text(channel, "link")
        ).strip()

        for cat in channel.findall("wp:category", consts.NS):
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
            if post_type == consts.ARTICLE_POST_TYPE:
                articles.append(item)
                self.article_items[post_id] = item
                link = element_text(item, "link")
                if link:
                    self.article_by_link[link_key(link)] = post_id
            elif post_type == "post":
                self.issue_posts[post_id] = item
            elif post_type == "page":
                if element_text(item, "wp:status") == "publish":
                    self.page_items.append(item)
            elif post_type == "nav_menu_item":
                self.menu_items.append(item)
            elif post_type == "attachment":
                url = element_text(item, "wp:attachment_url")
                if url:
                    parent = element_text(item, "wp:post_parent").strip()
                    self.attachments[post_id] = url
                    self.attachment_parents[post_id] = parent
                    self.attachments_by_parent.setdefault(parent, []).append(
                        (post_id, url)
                    )
        return articles

    def category_lineage(self, slug):
        seen = []
        while slug and slug not in seen:
            seen.append(slug)
            slug = self.category_parents.get(slug)
        return seen

    def collection_category(self, item):
        """Return the (code, name) of the item's collection category, if any."""
        for slug in category_slugs(item):
            root = self.category_lineage(slug)[-1]
            if root in consts.COLLECTION_CATEGORIES:
                return consts.COLLECTION_CATEGORIES[root]
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

    def collection_issue(self, title, bucket):
        issue, _ = journal_models.Issue.objects.get_or_create(
            journal=self.journal,
            issue_title=title[:300],
            issue_type=self.get_issue_type(*bucket),
            defaults={"volume": 1, "issue": ""},
        )
        return issue

    def attach_issue_image(self, issue, meta):
        """Download the parent post's featured image into Issue.large_image.

        The hero image of each WP issue/collection page is its featured
        image (`_thumbnail_id` postmeta -> attachment post -> URL). Skipped
        when the issue already has one, so reruns do not re-download.
        """
        if self.dry_run or issue.large_image:
            return
        url = self.attachments.get((meta.get("_thumbnail_id") or "").strip())
        if not url:
            return
        try:
            with urllib.request.urlopen(
                url, timeout=consts.DOWNLOAD_TIMEOUT
            ) as response:
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

        title = html.unescape(element_text(item, "title")).strip()
        if not title:
            return None
        meta = collect_postmeta(item)
        release = html.unescape(meta.get("release_date") or "").strip()
        issue_date, years = parse_release_date(release)
        post_date = parse_date(element_text(item, "wp:post_date"))
        if issue_date is None:
            issue_date = post_date
        elif (
            post_date
            and post_date.year == issue_date.year
            and consts.BARE_YEAR_RE.fullmatch(release)
        ):
            # a bare year: use the post date so issues of the same year
            # keep their sequence
            issue_date = post_date

        serial_match = consts.ISSUE_TITLE_RE.match(title)
        numbered_match = consts.NUMBERED_ISSUE_RE.match(title)
        dated_issue = False
        if serial_match:
            volume, number = (int(group) for group in serial_match.groups())
            issue, _ = journal_models.Issue.objects.get_or_create(
                journal=self.journal,
                volume=volume,
                issue=str(number),
                issue_type=self.get_issue_type("issue", "Issue"),
            )
            dated_issue = True
        elif bucket and numbered_match:
            # e.g. JEP "Number 3-4 (Spring 1996-Winter 1997)": numbered
            # issues of a collection type, listed newest first with their
            # season/year label in the title
            number = consts.ISSUE_NUMBER_RANGE_RE.sub("-", numbered_match.group(1))
            issue, _ = journal_models.Issue.objects.get_or_create(
                journal=self.journal,
                volume=0,
                issue=number,
                issue_type=self.get_issue_type(*bucket),
            )
            label = title
            if release and not consts.BARE_YEAR_RE.fullmatch(release):
                label = "{} ({})".format(title, release)
            elif release:
                label = "{}, {}".format(title, release)
            issue.issue_title = label[:300]
            dated_issue = True
        elif bucket:
            issue = self.collection_issue(title, bucket)
        else:
            issue, _ = journal_models.Issue.objects.get_or_create(
                journal=self.journal,
                issue_title=title[:300],
                issue_type=self.get_issue_type("collection", "Collection"),
                defaults={"volume": 1, "issue": ""},
            )

        if issue_date:
            issue.date = issue_date
        description = (meta.get("description") or "").strip()
        if description:
            issue.issue_description = format_wp_html(description)
        issue.save()

        if dated_issue and years:
            self.issue_max_year[issue.pk] = years[-1]
        self.attach_issue_image(issue, meta)
        self.issue_cache[post_id] = issue
        self.touched_issues[issue.pk] = (issue, item)
        return issue

    def match_keys(self, item, meta):
        """All the case-insensitive tokens an article can be selected by.

        Covers the article's own WordPress post id, slug and title, every
        category slug and name in its lineage, and its parent (post_add)
        post's id, slug and title, so --exclude/--only accept whichever
        form is most readable.
        """
        keys = {
            element_text(item, "wp:post_id"),
            element_text(item, "wp:post_name").strip().lower(),
            html.unescape(element_text(item, "title")).strip().lower(),
        }
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
            keys.add(html.unescape(element_text(parent, "title")).strip().lower())
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
            id_type=consts.IDENTIFIER_TYPE,
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

    def pdf_attachments(self, wp_id, meta):
        """PDF files uploaded to this article. The `pdf` postmeta is only
        trusted when it points at one of the article's own uploads: in the
        EJP export every `pdf` field points at the same placeholder file."""
        candidates = []
        for attachment_id, url in self.attachments_by_parent.get(wp_id, []):
            if url.lower().split("?")[0].endswith(".pdf"):
                candidates.append((attachment_id, url))
        meta_pdf = (meta.get("pdf") or "").strip()
        if (
            meta_pdf in self.attachments
            and self.attachment_parents.get(meta_pdf) == wp_id
            and meta_pdf not in {c[0] for c in candidates}
        ):
            candidates.append((meta_pdf, self.attachments[meta_pdf]))
        return candidates

    def same_site(self, url):
        def host(value):
            netloc = urlsplit(value).netloc.lower()
            return netloc[4:] if netloc.startswith("www.") else netloc

        return bool(host(url)) and host(url) == host(self.site_url)

    def download(self, url):
        if url not in self.image_cache:
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": consts.USER_AGENT}
                )
                with urllib.request.urlopen(
                    request, timeout=consts.DOWNLOAD_TIMEOUT
                ) as response:
                    self.image_cache[url] = response.read()
            except Exception as exc:
                self.log("  ! could not download {}: {}".format(url, exc))
                self.image_cache[url] = None
        return self.image_cache[url]

    def localise_images(self, body):
        """Download the images the body embeds from the WordPress site.

        Returns the body with each <img> src rewritten to a bare file name
        and the list of (file name, bytes) to store against the galley.
        Janeway serves galley images by their original file name relative
        to the article URL, so a bare name is all the src needs. Images
        hosted elsewhere are left untouched.
        """
        names = {}  # url -> file name
        images = []

        def replace(match):
            tag = match.group()
            src_match = consts.IMG_SRC_RE.search(tag)
            if not src_match:
                return tag
            url = html.unescape(src_match.group(1).strip())
            if not self.same_site(url):
                return tag
            if url not in names:
                data = self.download(url)
                if data is None:
                    self.stats["galley_images_failed"] += 1
                    return tag
                name = os.path.basename(urlsplit(url).path) or "image"
                taken = set(names.values())
                if name in taken:
                    name = "{}-{}".format(len(taken) + 1, name)
                names[url] = name
                images.append((name, data))
            tag = consts.IMG_RESPONSIVE_ATTRS_RE.sub("", tag)
            return tag.replace(src_match.group(0), 'src="{}"'.format(names[url]))

        return consts.IMG_TAG_RE.sub(replace, body), images

    def attach_galleys(self, article, wp_id, meta):
        for galley in core_models.Galley.objects.filter(article=article):
            galley_file = galley.file
            for image in galley.images.all():
                image.delete()  # also unlinks the file on disk
            galley.delete()
            if galley_file:
                galley_file.delete()

        body = build_body_html(meta)
        images = []
        if body and self.download_images:
            body, images = self.localise_images(body)
        if body:
            content = ContentFile(
                body.encode("utf-8"),
                name="{}.html".format(slugify(article.title)[:60] or "article"),
            )
            saved_file = core_files.save_file_to_article(
                content,
                article,
                owner=None,
                label=consts.HTML_GALLEY_LABEL,
                is_galley=True,
            )
            saved_file.mime_type = "text/html"
            saved_file.save()
            galley = core_models.Galley.objects.create(
                article=article,
                file=saved_file,
                label=consts.HTML_GALLEY_LABEL,
                type="html",
            )
            for name, data in images:
                image_file = core_files.save_file_to_article(
                    ContentFile(data, name=name),
                    article,
                    owner=None,
                    label=consts.GALLEY_IMAGE_LABEL,
                    is_galley=False,
                )
                galley.images.add(image_file)
                self.stats["galley_images_added"] += 1

        if not self.download_pdfs:
            return
        for index, (_, pdf_url) in enumerate(self.pdf_attachments(wp_id, meta)):
            try:
                with urllib.request.urlopen(
                    pdf_url, timeout=consts.DOWNLOAD_TIMEOUT
                ) as response:
                    pdf_bytes = response.read()
            except Exception as exc:
                self.log("  ! could not download {}: {}".format(pdf_url, exc))
                continue
            name = os.path.basename(pdf_url.split("?")[0]) or "article.pdf"
            label = (
                consts.PDF_GALLEY_LABEL
                if index == 0
                else "{} ({})".format(consts.PDF_GALLEY_LABEL, name)
            )
            saved_file = core_files.save_file_to_article(
                ContentFile(pdf_bytes, name=name),
                article,
                owner=None,
                label=label,
                is_galley=True,
            )
            core_models.Galley.objects.create(
                article=article,
                file=saved_file,
                label=label,
                type="pdf",
            )
            self.stats["pdf_galleys_added"] += 1

    def block_publication_date(self, meta, hint):
        """The date shown on the site comes from a "Publication Date" block
        when there is one, not from the WP post date."""
        index = 0
        while True:
            text = meta.get("blocks_{}_text".format(index))
            title = meta.get("blocks_{}_title".format(index))
            if text is None and title is None:
                return None
            if (title or "").strip().lower() in consts.DATE_BLOCK_TITLES and text:
                parsed = parse_block_date(text, hint)
                if parsed and 1900 < parsed.year < 2100:
                    return parsed
            index += 1

    def import_article(self, item):
        wp_id = element_text(item, "wp:post_id")
        status = element_text(item, "wp:status")
        title = fix_mojibake(html.unescape(element_text(item, "title")).strip())
        meta = collect_postmeta(item)

        if self.filtered_out(item, meta):
            return
        if status != "publish" and not self.include_unpublished:
            self.stats["articles_skipped_status"] += 1
            return
        if not title:
            title = "Untitled (WordPress post {})".format(wp_id)
        published = status == "publish"
        post_date = parse_date(element_text(item, "wp:post_date_gmt")) or parse_date(
            element_text(item, "wp:post_date")
        )

        bucket = self.collection_category(item)
        issue = self.issue_for_post((meta.get("post_add") or "").strip(), bucket)
        if issue is None and bucket:
            # catch-all collection for posts with no parent post
            issue = self.collection_issue(bucket[1], bucket)
            self.touched_issues.setdefault(issue.pk, (issue, None))

        block_date = self.block_publication_date(meta, post_date)
        date_published = block_date or post_date
        max_year = self.issue_max_year.get(issue.pk) if issue else None
        if (
            not block_date
            and date_published
            and max_year
            and date_published.year > max_year
        ):
            # front matter and recovered texts were added to WP years after
            # the issue came out; the site shows the issue's year for them
            date_published = issue.date

        section, _ = submission_models.Section.objects.get_or_create(
            journal=self.journal,
            name=consts.DEFAULT_SECTION,
        )

        article = self.existing_article(wp_id)
        created = article is None
        if created:
            article = submission_models.Article(
                journal=self.journal,
                is_import=True,
            )

        article.title = title[:999]
        article.abstract = format_abstract(meta.get("intro")) or None
        article.section = section
        article.stage = (
            submission_models.STAGE_PUBLISHED
            if published
            else submission_models.STAGE_UNSUBMITTED
        )
        article.date_published = date_published if published else None
        article.date_submitted = post_date

        if meta.get("citation_text") and meta.get("hide_citation") != "1":
            article.custom_how_to_cite = meta["citation_text"].strip()
        else:
            article.custom_how_to_cite = None

        summary = (meta.get("short_description") or "").strip()
        article.non_specialist_summary = wptexturize(fix_mojibake(summary)) or None
        article.save()

        if created:
            identifier_models.Identifier.objects.create(
                id_type=consts.IDENTIFIER_TYPE,
                identifier=wp_id,
                article=article,
            )

        self.create_frozen_authors(article, meta)
        self.attach_keywords(article, meta)
        # galley file writes cannot be rolled back, so dry runs skip them
        if not self.dry_run:
            self.attach_galleys(article, wp_id, meta)

        if issue:
            issue.articles.add(article)
            article.primary_issue = issue
            article.save()
            self.stats["issues_linked"] += 1
            # reruns may map the article to a different issue (e.g. after
            # a change in how parent posts are typed): drop the old link
            for other in journal_models.Issue.objects.filter(
                journal=self.journal, articles=article
            ).exclude(pk=issue.pk):
                other.articles.remove(article)
                journal_models.ArticleOrdering.objects.filter(
                    issue=other, article=article
                ).delete()

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

    # --- Ordering ----------------------------------------------------------

    def fetch_live_order(self, parent_item):
        """Fetch the issue/collection page from the live WordPress site and
        return the permalink paths of the articles in the order shown.

        The order editors curated on the site (a post ordering plugin) is
        not part of the WXR export, so the page itself is the only source.
        """
        url = element_text(parent_item, "link").strip()
        if not url:
            return None
        if url in self.live_order_cache:
            return self.live_order_cache[url]
        paths = None
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": consts.USER_AGENT}
            )
            with urllib.request.urlopen(
                request, timeout=consts.DOWNLOAD_TIMEOUT
            ) as response:
                page = response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            self.log("  ! could not fetch live order from {}: {}".format(url, exc))
        else:
            paths = []
            for match in consts.ANCHOR_RE.finditer(page):
                path = link_key(html.unescape(match.group(1)))
                if path in self.article_by_link and path not in paths:
                    paths.append(path)
                # articles whose permalink changed are matched by title
                path_title = normalise_title(strip_tags(match.group(2)))
                if path_title and (path, path_title) not in paths:
                    paths.append((path, path_title))
        self.live_order_cache[url] = paths
        return paths

    @staticmethod
    def live_positions(live_paths, entries):
        """Map article pk -> position on the live page, matching by
        permalink first and by title for articles whose slug changed."""
        by_path = {}
        by_title = {}
        for article, item in entries:
            if item is None:
                continue
            link = element_text(item, "link")
            if link:
                by_path[link_key(link)] = article.pk
            by_title.setdefault(
                normalise_title(element_text(item, "title")), article.pk
            )
        positions = {}
        for path in live_paths:
            if isinstance(path, tuple):
                pk = by_title.get(path[1])
            else:
                pk = by_path.get(path)
            if pk is not None and pk not in positions:
                positions[pk] = len(positions)
        return positions

    def order_issue_articles(self, issue, parent_item):
        articles = list(issue.articles.all())
        if not articles:
            return
        wp_ids = dict(
            identifier_models.Identifier.objects.filter(
                article__in=articles, id_type=consts.IDENTIFIER_TYPE
            ).values_list("article_id", "identifier")
        )
        entries = [
            (article, self.article_items.get(wp_ids.get(article.pk)))
            for article in articles
        ]

        live_paths = None
        if self.live_order and parent_item is not None:
            live_paths = self.fetch_live_order(parent_item)
        position = {}
        if live_paths:
            position = self.live_positions(live_paths, entries)
        if position:
            listed = [e for e in entries if e[0].pk in position]
            listed.sort(key=lambda e: position[e[0].pk])
            unlisted = [e for e in entries if e[0].pk not in position]
            ordered = listed + fallback_order(unlisted)
            self.stats["issues_ordered_from_live_site"] += 1
        else:
            ordered = fallback_order(entries)

        journal_models.ArticleOrdering.objects.filter(issue=issue).delete()
        for order, (article, _) in enumerate(ordered, start=1):
            journal_models.ArticleOrdering.objects.create(
                article=article,
                issue=issue,
                section=article.section,
                order=order,
            )
        self.stats["issues_ordered"] += 1

    def apply_article_ordering(self):
        for issue, parent_item in self.touched_issues.values():
            try:
                with transaction.atomic():
                    self.order_issue_articles(issue, parent_item)
            except Exception as exc:
                self.stats["errors"] += 1
                self.log("  ! error ordering '{}': {}".format(issue.display_title, exc))

    # --- Pages and navigation ----------------------------------------------

    def rewrite_page_links(self, text):
        """Point links to other imported WP pages at their Janeway URL."""
        slugs = {element_text(p, "wp:post_name") for p in self.page_items}
        site_host = urlsplit(self.site_url).netloc.lower()

        def replace(match):
            url = match.group(2)
            parts = urlsplit(url)
            if parts.netloc.lower() != site_host:
                return match.group(0)
            slug = parts.path.strip("/").rsplit("/", 1)[-1]
            if slug in slugs:
                return '{}="/site/{}/"'.format(match.group(1), slug)
            return match.group(0)

        return consts.HREF_RE.sub(replace, text)

    def build_page_html(self, item, meta):
        """Pages in the export keep their content in ACF "sections" made of
        a title, a text and optional contact/link blocks."""
        parts = []
        encoded = element_text(item, "content:encoded")
        if encoded.strip():
            parts.append(format_wp_html(encoded))
        section = 0
        while any(key.startswith("sections_{}_".format(section)) for key in meta):
            prefix = "sections_{}_".format(section)
            title = (meta.get(prefix + "title") or "").strip()
            if title:
                parts.append("<h2>{}</h2>".format(html.escape(title)))
            if (meta.get(prefix + "text") or "").strip():
                parts.append(format_wp_html(meta[prefix + "text"]))
            contact = 0
            while meta.get("{}contacts_{}_text".format(prefix, contact)) is not None:
                text = meta["{}contacts_{}_text".format(prefix, contact)]
                if text.strip():
                    parts.append(
                        '<div class="contact">{}</div>'.format(format_wp_html(text))
                    )
                contact += 1
            block = 0
            while any(
                key.startswith("{}blocks_{}_".format(prefix, block)) for key in meta
            ):
                block_prefix = "{}blocks_{}_".format(prefix, block)
                block_title = (meta.get(block_prefix + "title") or "").strip()
                text = meta.get(block_prefix + "text") or ""
                link = (meta.get(block_prefix + "link") or "").strip()
                if not block_title:
                    # link tiles keep their label inside the text field
                    block_title, text = strip_tags(text), ""
                if block_title:
                    heading = html.escape(block_title)
                    if link:
                        heading = '<a href="{}">{}</a>'.format(
                            html.escape(link), heading
                        )
                    parts.append("<h3>{}</h3>".format(heading))
                subtitle = (meta.get(block_prefix + "subtitle") or "").strip()
                if subtitle:
                    parts.append("<p><em>{}</em></p>".format(html.escape(subtitle)))
                if text.strip():
                    parts.append(format_wp_html(text))
                block += 1
            section += 1
        return self.rewrite_page_links("\n".join(parts))

    def import_pages(self):
        content_type = ContentType.objects.get_for_model(self.journal)
        for item in self.page_items:
            meta = collect_postmeta(item)
            name = element_text(item, "wp:post_name").strip()
            title = html.unescape(element_text(item, "title")).strip()
            if (
                not name
                or not title
                or meta.get("_wp_page_template") == consts.HOME_PAGE_TEMPLATE
            ):
                continue
            content = self.build_page_html(item, meta)
            if not content.strip():
                continue
            page, created = cms_models.Page.objects.update_or_create(
                content_type=content_type,
                object_id=self.journal.pk,
                name=name,
                defaults={
                    "display_name": title[:100],
                    "content": content,
                    "is_markdown": False,
                },
            )
            self.imported_pages[element_text(item, "wp:post_id")] = page
            self.stats["pages_imported"] += 1
            self.log(
                "  {} page '{}' -> /site/{}/".format(
                    "+" if created else "~", title, name
                )
            )

    def create_page_navigation(self):
        """Recreate the WP menus that link to the imported pages."""
        content_type = ContentType.objects.get_for_model(self.journal)
        for menu_slug, group_name in consts.PAGE_MENUS:
            entries = []
            for item in self.menu_items:
                meta = collect_postmeta(item)
                menus = [
                    c.get("nicename")
                    for c in item.findall("category")
                    if c.get("domain") == "nav_menu"
                ]
                page = self.imported_pages.get(meta.get("_menu_item_object_id", ""))
                if menu_slug not in menus or meta.get("_menu_item_object") != "page":
                    continue
                if page is None:
                    continue
                entries.append((int(element_text(item, "wp:menu_order") or 0), page))
            if not entries:
                continue
            entries.sort(key=lambda entry: entry[0])
            top_nav = None
            if group_name:
                top_nav, _ = cms_models.NavigationItem.objects.get_or_create(
                    content_type=content_type,
                    object_id=self.journal.pk,
                    link_name=group_name,
                    top_level_nav=None,
                    defaults={
                        "has_sub_nav": True,
                        "sequence": consts.PAGES_NAV_SEQUENCE,
                    },
                )
            for sequence, page in entries:
                cms_models.NavigationItem.objects.update_or_create(
                    content_type=content_type,
                    object_id=self.journal.pk,
                    link_name=page.display_name,
                    top_level_nav=top_nav,
                    defaults={
                        "link": "/site/{}/".format(page.name),
                        "page": page,
                        "sequence": consts.PAGES_NAV_SEQUENCE + sequence,
                    },
                )

    def create_collection_navigation(self):
        """Create nav entries for the collection issue types.

        Follows the same link convention as
        cms.NavigationItem.toggle_collection_nav. Types in
        consts.TOP_LEVEL_COLLECTIONS get a top-level item, the rest a sub-item
        under consts.COLLECTIONS_NAV_NAME. Issue types without issues (e.g. after
        an --exclude run) get no item.
        """
        content_type = ContentType.objects.get_for_model(self.journal)
        top_nav, _ = cms_models.NavigationItem.objects.get_or_create(
            content_type=content_type,
            object_id=self.journal.pk,
            link_name=consts.COLLECTIONS_NAV_NAME,
            defaults={"has_sub_nav": True},
        )
        active_sub_items = 0
        for sequence, (code, name) in enumerate(consts.COLLECTION_CATEGORIES.values()):
            parent = None if code in consts.TOP_LEVEL_COLLECTIONS else top_nav
            nav_items = cms_models.NavigationItem.objects.filter(
                content_type=content_type,
                object_id=self.journal.pk,
                link_name=name,
                top_level_nav=parent,
            )
            if journal_models.Issue.objects.filter(
                journal=self.journal, issue_type__code=code
            ).exists():
                if parent is not None:
                    active_sub_items += 1
                if not nav_items.exists():
                    cms_models.NavigationItem.objects.create(
                        content_type=content_type,
                        object_id=self.journal.pk,
                        link_name=name,
                        top_level_nav=parent,
                        link="/collections/{}".format(code),
                        sequence=sequence,
                    )
            else:
                nav_items.delete()
        if not active_sub_items:
            top_nav.delete()

    def run(self):
        articles = self.load()
        self.log(
            "Found {} '{}' items ({} issue candidate posts, {} pages, {} attachments)".format(
                len(articles),
                consts.ARTICLE_POST_TYPE,
                len(self.issue_posts),
                len(self.page_items),
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
        self.log("Ordering articles within {} issues".format(len(self.touched_issues)))
        self.apply_article_ordering()
        self.create_collection_navigation()
        if not self.skip_pages:
            self.log("Importing pages")
            self.import_pages()
            self.create_page_navigation()
        for token in sorted(
            (self.exclude_tokens | self.only_tokens) - self.matched_tokens
        ):
            self.log(
                "  ! warning: filter token '{}' did not match any article".format(token)
            )
        return self.stats


def import_wordpress_export(journal, xml_path, stdout=None, dry_run=False, **options):
    """Run a full import inside a transaction and return the stats.

    With ``dry_run`` every database change is rolled back at the end; the
    importer also skips file writes (galleys, PDFs, images) in that mode
    because those cannot be rolled back.
    """
    importer = WordPressImporter(
        journal, xml_path, stdout=stdout, dry_run=dry_run, **options
    )
    try:
        with transaction.atomic():
            importer.run()
            if dry_run:
                raise DryRunRollback()
    except DryRunRollback:
        importer.log("\nDry run: all database changes rolled back.")
    return importer.stats
