"""Import a WordPress WXR export into a Janeway journal.

The WXR export of a site built on a custom "articles" post type is turned
into articles (with HTML galleys, authors and keywords), issues and
collections (from the posts the articles are attached to), CMS pages and
navigation items. The command line interface lives in
management/commands/import_wordpress.py; use :func:`import_wordpress_export`
or :class:`WordPressImporter` directly from code.

Modules:

- ``consts``: constants and regular expressions
- ``text``: WordPress text formatting (wpautop, wptexturize, shortcodes)
- ``wxr``: reading the export (elements, postmeta, authors, dates, ordering)
- ``importer``: the importer itself
"""

from . import consts
from .consts import (
    COLLECTION_CATEGORIES,
    COLLECTIONS_NAV_NAME,
    DEFAULT_SECTION,
    IDENTIFIER_TYPE,
    TOP_LEVEL_COLLECTIONS,
)
from .importer import DryRunRollback, WordPressImporter, import_wordpress_export
from .text import (
    fix_mojibake,
    format_abstract,
    format_wp_html,
    strip_tags,
    wpautop,
    wptexturize,
)
from .wxr import (
    fallback_order,
    make_aware,
    parse_block_date,
    parse_date,
    parse_release_date,
    split_authors,
)

__all__ = [
    "COLLECTION_CATEGORIES",
    "COLLECTIONS_NAV_NAME",
    "DEFAULT_SECTION",
    "IDENTIFIER_TYPE",
    "TOP_LEVEL_COLLECTIONS",
    "DryRunRollback",
    "WordPressImporter",
    "consts",
    "fallback_order",
    "fix_mojibake",
    "format_abstract",
    "format_wp_html",
    "import_wordpress_export",
    "make_aware",
    "parse_block_date",
    "parse_date",
    "parse_release_date",
    "split_authors",
    "strip_tags",
    "wpautop",
    "wptexturize",
]
