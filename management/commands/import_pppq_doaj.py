"""Import a journal's back-content from a DOAJ articles XML export plus an
OJS file tree.

The DOAJ XML (schema ``doajArticles.xsd``) provides one ``<record>`` per
article. Files live under ``<files_root>/articles/<ojs_id>/public/`` where the
OJS id is the trailing integer of each record's ``fullTextUrl``.

Records are routed by title:

* ``front cover ...`` -> Article in the "Front Cover" section
* ``back cover ...``  -> Article in the "Back Cover" section
* ``full issue ...``  -> IssueGalley on the record's issue (no Article)
* anything else       -> Article in the "Article" section
"""
import os
import xml.etree.ElementTree as ET

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core import files as core_files
from core.models import Account
from identifiers import models as identifiers_models
from journal import models as journal_models
from production.logic import save_galley
from submission import models as submission_models

from plugins.imports.utils import DummyRequest, get_aware_datetime

PPPQ_OJS_ID = "pppq_ojs_id"
DEFAULT_LANGUAGE = "eng"
PDF_MAGIC = b"%PDF"


class DryRunRollback(Exception):
    """Raised at the end of a dry run to roll back the enclosing transaction."""


def element_text(record, tag):
    """Return the stripped text of a child element, or None if absent/empty."""
    child = record.find(tag)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


def parse_ojs_id(full_text_url):
    """Return the trailing integer of a fullTextUrl as a string, else None."""
    if not full_text_url:
        return None
    trailing = ""
    for char in reversed(full_text_url.strip()):
        if char.isdigit():
            trailing = char + trailing
        else:
            break
    return trailing or None


def route_for_title(title):
    """Return one of 'front_cover', 'back_cover', 'full_issue', 'article'."""
    normalised = (title or "").strip().lower()
    if normalised.startswith("front cover"):
        return "front_cover"
    if normalised.startswith("back cover"):
        return "back_cover"
    if normalised.startswith("full issue"):
        return "full_issue"
    return "article"


SECTION_NAMES = {
    "front_cover": "Front Cover",
    "back_cover": "Back Cover",
    "article": "Article",
}


def parse_authors(record):
    """Return a list of (first_name, last_name, email) tuples in record order.

    A record may have zero authors. Names are split on the last space so that
    single-token names land in the last name.
    """
    authors = []
    authors_el = record.find("authors")
    if authors_el is None:
        return authors
    for author_el in authors_el.findall("author"):
        name_el = author_el.find("name")
        name = ""
        if name_el is not None and name_el.text:
            name = name_el.text.strip()
        if not name:
            continue
        if " " in name:
            first_name, last_name = name.rsplit(" ", 1)
        else:
            first_name, last_name = "", name
        email_el = author_el.find("email")
        email = None
        if email_el is not None and email_el.text:
            email = email_el.text.strip() or None
        authors.append((first_name.strip(), last_name.strip(), email))
    return authors


def read_public_file(files_root, ojs_id):
    """Locate the public file for an OJS article.

    Returns a ``(name, content, candidate_count)`` tuple with PDF magic-byte
    correction applied, or None if there is no usable file. The first file
    (alphabetically) is used; ``candidate_count`` lets the caller warn when
    more than one file was present. ``.DS_Store`` entries are ignored.
    """
    public_dir = os.path.join(files_root, "articles", str(ojs_id), "public")
    if not os.path.isdir(public_dir):
        return None
    candidates = [
        entry
        for entry in sorted(os.listdir(public_dir))
        if entry != ".DS_Store"
        and os.path.isfile(os.path.join(public_dir, entry))
    ]
    if not candidates:
        return None
    name = candidates[0]
    path = os.path.join(public_dir, name)
    with open(path, "rb") as open_file:
        content = open_file.read()
    if content[:4] == PDF_MAGIC and not name.lower().endswith(".pdf"):
        name = os.path.splitext(name)[0] + ".pdf"
    return name, content, len(candidates)


def get_or_create_issue(journal, volume, issue_label, date_published):
    """Get or create a serial Issue for (journal, volume, issue label)."""
    try:
        volume_number = int(volume)
    except (TypeError, ValueError):
        volume_number = 0
    issue_label = issue_label or "1"

    # The ``issue_type__code`` __-lookup filters the get_or_create match but is
    # stripped by Django before ``.create()``, so a newly created issue has no
    # issue_type yet; it is back-filled in the ``if created:`` block below.
    issue, created = journal_models.Issue.objects.get_or_create(
        journal=journal,
        volume=volume_number,
        issue=issue_label,
        issue_type__code="issue",
        defaults={
            "date": date_published,
        },
    )
    if created:
        issue.issue_type = journal_models.IssueType.objects.get(
            code="issue", journal=journal,
        )
        if date_published:
            issue.date = date_published
        issue.save()
    return issue


class Command(BaseCommand):
    """CLI importer for the PPPQ DOAJ XML export and OJS file tree."""

    help = "Import a journal's back-content from a DOAJ XML export and OJS files"

    def add_arguments(self, parser):
        parser.add_argument("xml_file")
        parser.add_argument("files_root")
        parser.add_argument("journal_code")
        parser.add_argument("--owner-id", type=int, default=1)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            journal = journal_models.Journal.objects.get(
                code=options["journal_code"],
            )
        except journal_models.Journal.DoesNotExist:
            raise CommandError(
                "No journal found with code '%s'" % options["journal_code"]
            )

        try:
            owner = Account.objects.get(pk=options["owner_id"])
        except Account.DoesNotExist:
            raise CommandError(
                "No account found with id %s" % options["owner_id"]
            )

        files_root = options["files_root"]
        dry_run = options["dry_run"]
        request = DummyRequest(owner, journal)

        tree = ET.parse(options["xml_file"])
        records = tree.getroot().findall("record")

        results = {
            "articles_created": 0,
            "articles_updated": 0,
            "issue_galleys": 0,
            "skipped": 0,
            "no_galley": [],
            "full_issue_no_pdf": [],
            "multiple_files": [],
            "errors": [],
        }

        try:
            with transaction.atomic():
                for record in records:
                    self.handle_record(
                        record, journal, owner, request, files_root,
                        dry_run, results,
                    )
                if dry_run:
                    raise DryRunRollback()
        except DryRunRollback:
            pass

        self.print_summary(results, dry_run)

    def handle_record(self, record, journal, owner, request, files_root,
                      dry_run, results):
        title = element_text(record, "title") or ""
        full_text_url = element_text(record, "fullTextUrl")
        ojs_id = parse_ojs_id(full_text_url)

        if not ojs_id:
            results["skipped"] += 1
            results["errors"].append(
                "Could not parse an OJS id from fullTextUrl '%s' (title: %s)"
                % (full_text_url, title)
            )
            return

        route = route_for_title(title)

        try:
            with transaction.atomic():
                if route == "full_issue":
                    self.import_full_issue(
                        record, journal, request, files_root, ojs_id,
                        dry_run, results,
                    )
                else:
                    self.import_article(
                        record, journal, owner, request, files_root, ojs_id,
                        route, title, dry_run, results,
                    )
        except Exception as error:
            results["errors"].append(
                "OJS id %s: %s" % (ojs_id, error)
            )

    def import_article(self, record, journal, owner, request, files_root,
                       ojs_id, route, title, dry_run, results):
        doi = element_text(record, "doi")
        article, created = self.get_or_create_article(journal, ojs_id, doi)

        section, _ = submission_models.Section.objects.get_or_create(
            journal=journal,
            name=SECTION_NAMES[route],
        )

        date_published = None
        publication_date = element_text(record, "publicationDate")
        if publication_date:
            date_published = get_aware_datetime(publication_date)

        article.journal = journal
        article.title = title
        article.abstract = element_text(record, "abstract") or ""
        article.language = element_text(record, "language") or DEFAULT_LANGUAGE
        article.date_published = date_published
        article.stage = submission_models.STAGE_PUBLISHED
        article.is_import = True
        article.owner = owner
        article.first_page = self.parse_page(element_text(record, "startPage"))
        article.last_page = self.parse_page(element_text(record, "endPage"))
        article.section = section
        article.save()

        identifiers_models.Identifier.objects.get_or_create(
            id_type=PPPQ_OJS_ID,
            identifier=ojs_id,
            article=article,
        )
        if doi:
            identifiers_models.Identifier.objects.get_or_create(
                id_type="doi",
                identifier=doi,
                article=article,
            )

        issue = get_or_create_issue(
            journal,
            element_text(record, "volume"),
            element_text(record, "issue"),
            date_published,
        )
        article.primary_issue = issue
        article.save()
        issue.articles.add(article)

        self.import_authors(record, article)

        public_file = read_public_file(files_root, ojs_id)
        if public_file:
            name, content, candidate_count = public_file
            if candidate_count > 1:
                results["multiple_files"].append(ojs_id)
            if not dry_run:
                django_file = ContentFile(content, name=name)
                existing = article.galley_set.filter(public=True).first()
                if existing:
                    # Idempotent re-run: overwrite the existing galley's file
                    # rather than creating a duplicate Galley (mirrors
                    # IssueGalley.replace_file).
                    core_files.overwrite_file(
                        django_file,
                        existing.file,
                        ("articles", article.pk),
                    )
                else:
                    save_galley(
                        article, request, django_file,
                        is_galley=True, public=True,
                    )
        else:
            results["no_galley"].append(ojs_id)

        if created:
            results["articles_created"] += 1
        else:
            results["articles_updated"] += 1

    def import_full_issue(self, record, journal, request, files_root, ojs_id,
                          dry_run, results):
        date_published = None
        publication_date = element_text(record, "publicationDate")
        if publication_date:
            date_published = get_aware_datetime(publication_date)

        issue = get_or_create_issue(
            journal,
            element_text(record, "volume"),
            element_text(record, "issue"),
            date_published,
        )

        public_file = read_public_file(files_root, ojs_id)
        if not public_file:
            results["full_issue_no_pdf"].append(ojs_id)
            return

        name, content, candidate_count = public_file
        if candidate_count > 1:
            results["multiple_files"].append(ojs_id)
        if not dry_run:
            django_file = ContentFile(content, name=name)
            existing = journal_models.IssueGalley.objects.filter(
                issue=issue,
            ).first()
            if existing:
                existing.replace_file(django_file)
            else:
                file_obj = core_files.save_file(
                    request,
                    django_file,
                    label=issue.issue_title or "Full Issue",
                    public=True,
                    path_parts=(
                        journal_models.IssueGalley.FILES_PATH, issue.pk,
                    ),
                )
                journal_models.IssueGalley.objects.create(
                    file=file_obj, issue=issue,
                )
        results["issue_galleys"] += 1

    def get_or_create_article(self, journal, ojs_id, doi):
        """Return (article, created) using idempotent identifier lookups."""
        existing = identifiers_models.Identifier.objects.filter(
            id_type=PPPQ_OJS_ID,
            identifier=ojs_id,
            article__journal=journal,
        ).first()
        if existing:
            return existing.article, False

        if doi:
            existing = identifiers_models.Identifier.objects.filter(
                id_type="doi",
                identifier=doi,
                article__journal=journal,
            ).first()
            if existing:
                return existing.article, False

        article = submission_models.Article.objects.create(
            journal=journal,
            title="",
            is_import=True,
        )
        return article, True

    def import_authors(self, record, article):
        """Replace the article's frozen authors from the record, in order."""
        submission_models.FrozenAuthor.objects.filter(article=article).delete()
        for order, (first_name, last_name, email) in enumerate(
            parse_authors(record), start=1,
        ):
            submission_models.FrozenAuthor.objects.create(
                article=article,
                first_name=first_name,
                last_name=last_name,
                frozen_email=email or "",
                order=order,
            )

    def parse_page(self, value):
        if value and value.isdigit():
            return int(value)
        return None

    def print_summary(self, results, dry_run):
        if dry_run:
            print("DRY RUN - no changes were persisted.")
        print("Articles created: %d" % results["articles_created"])
        print("Articles updated: %d" % results["articles_updated"])
        print("Issue galleys attached: %d" % results["issue_galleys"])
        print("Records skipped: %d" % results["skipped"])

        print(
            "Articles with no galley (%d): %s"
            % (
                len(results["no_galley"]),
                ", ".join(results["no_galley"]) or "none",
            )
        )
        print(
            "Full-issue records with no PDF (%d): %s"
            % (
                len(results["full_issue_no_pdf"]),
                ", ".join(results["full_issue_no_pdf"]) or "none",
            )
        )
        print(
            "Records with multiple public files (first used) (%d): %s"
            % (
                len(results["multiple_files"]),
                ", ".join(results["multiple_files"]) or "none",
            )
        )
        print("Errors (%d):" % len(results["errors"]))
        for error in results["errors"]:
            print("  %s" % error)
