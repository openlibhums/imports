"""Constants and regular expressions used by the WordPress WXR importer.

Regular expression constants end in ``_RE``; ``*_PATTERN`` constants are
plain strings meant to be embedded in other expressions.
"""

import re

# --- WXR export ------------------------------------------------------------

NS = {
    "wp": "http://wordpress.org/export/1.2/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "excerpt": "http://wordpress.org/export/1.2/excerpt/",
    "dc": "http://purl.org/dc/elements/1.1/",
}
ARTICLE_POST_TYPE = "articles"
IDENTIFIER_TYPE = "wordpressid"
WP_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
HOME_PAGE_TEMPLATE = "page-home.php"
# Leftover ACF field that holds the same boilerplate text in every post
IGNORED_BODY_META = {"text0000"}
# Article "blocks" whose text holds the publication date shown on the site
DATE_BLOCK_TITLES = {
    "publication date",
    "publication",
    "date",
    "data",
    "data di pubblicazione",
    "fecha de publicación",
}

INVALID_XML_CHARS_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
# Author strings are free text: "A, B", "A & B", "A and B", "A with B"
AUTHOR_SPLIT_RE = re.compile(r"\s*(?:,|&|\band\b|\bwith\b)\s*")

# --- Janeway target --------------------------------------------------------

DEFAULT_SECTION = "Article"
HTML_GALLEY_LABEL = "HTML"
PDF_GALLEY_LABEL = "PDF"
GALLEY_IMAGE_LABEL = "Image File"

# Top-level WP categories imported as collections, mapped to
# (issue type code, issue type name). Articles under any other category
# are attached to regular issues via their post_add parent.
# TODO: These are specific to EJP,think of how to provide these from CLI instead
COLLECTION_CATEGORIES = {
    "discourse": ("discourse", "Discourse"),
    "symposia": ("symposia", "Symposia"),
    "features": ("features", "Features"),
    "articles": ("articles", "Articles"),
    "jep": ("jep", "The JEP"),
}
COLLECTIONS_NAV_NAME = "Collections"
# Collection types that get their own top-level nav item instead of a
# sub-item under COLLECTIONS_NAV_NAME (the JEP is the journal's archive)
TOP_LEVEL_COLLECTIONS = {"jep"}

# WordPress nav menus whose page entries are recreated as Janeway nav
# items: menu slug -> name of the top-level item grouping them (None for
# top-level items)
PAGE_MENUS = (("about", "About"), ("journal", None))
PAGES_NAV_SEQUENCE = 50

# --- Issues ----------------------------------------------------------------

# "Vol. 8, No. 2"
ISSUE_TITLE_RE = re.compile(r"^Vol\.?\s*(\d+)\s*,?\s*No\.?\s*(\d+)$", re.I)
# "Number 3-4", "No. 12", "Issue 7": numbered issues without a volume
NUMBERED_ISSUE_RE = re.compile(
    r"^(?:Number|No\.?|Issue|N[úu]mero)\s*(\d+(?:\s*[-–]\s*\d+)?)$", re.I
)
# the dash of a double number, "3 - 4" or "3–4"
ISSUE_NUMBER_RANGE_RE = re.compile(r"\s*[-–]\s*")
FRONT_MATTER_RE = re.compile(r"^(?:table of contents|contributors)\b", re.I)
BARE_YEAR_RE = re.compile(r"\d{4}")

# --- Dates -----------------------------------------------------------------

MONTHS = {}
for _index, _names in enumerate(
    (
        ("january", "jan", "enero", "gennaio", "janvier"),
        ("february", "feb", "febrero", "febbraio", "février"),
        ("march", "mar", "marzo", "mars"),
        ("april", "apr", "abril", "aprile", "avril"),
        ("may", "mayo", "maggio", "mai"),
        ("june", "jun", "junio", "giugno", "juin"),
        ("july", "jul", "julio", "luglio", "juillet"),
        ("august", "aug", "agosto", "août"),
        ("september", "sep", "sept", "septiembre", "setiembre", "settembre"),
        ("october", "oct", "octubre", "ottobre", "octobre"),
        ("november", "nov", "noviembre", "novembre"),
        ("december", "dec", "diciembre", "dicembre", "décembre"),
    ),
    start=1,
):
    for _name in _names:
        MONTHS[_name] = _index
MONTH_NAMES_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))
SEASON_MONTHS = {"winter": 1, "spring": 3, "summer": 6, "fall": 9, "autumn": 9}

YEAR_RE = re.compile(r"\b(1[89]\d\d|20\d\d)\b")
# "February 2020" inside a free-text release date
RELEASE_MONTH_YEAR_RE = re.compile(
    r"\b(" + MONTH_NAMES_PATTERN + r")\b\.?\s+(1[89]\d\d|20\d\d)"
)
SEASON_RE = re.compile(r"\b(winter|spring|summer|fall|autumn)\b")
# publication date blocks: "12th", "9 de febrero", "12/03/2021"...
ORDINAL_SUFFIX_RE = re.compile(r"(\d)(st|nd|rd|th)\b")
SPANISH_DE_RE = re.compile(r"\bde\b")
DATE_PUNCTUATION_RE = re.compile(r"[,.]")
NUMERIC_DATE_RE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})")
MONTH_DAY_YEAR_RE = re.compile(r"^(" + MONTH_NAMES_PATTERN + r")\s+(\d{1,2})\s+(\d{4})")
DAY_MONTH_YEAR_RE = re.compile(r"^(\d{1,2})\s+(" + MONTH_NAMES_PATTERN + r")\s+(\d{4})")
MONTH_YEAR_RE = re.compile(r"^(" + MONTH_NAMES_PATTERN + r")\s+(\d{4})")

# --- Text ------------------------------------------------------------------

WHITESPACE_RE = re.compile(r"\s+")
HTML_TAG_RE = re.compile(r"<[^>]+>")
CURLY_DOUBLE_QUOTES_RE = re.compile(r"[“”]")
CURLY_SINGLE_QUOTES_RE = re.compile(r"[‘’]")

# The site's old texts were converted from Mac Roman as if they were
# Latin-1, turning punctuation into stray accented capitals ("detailsÑwhich",
# "himselfÉ"). Only patterns that cannot occur in real words are replaced.
MOJIBAKE_RULES = (
    (re.compile(r"(?<=[a-zà-ÿ0-9,.;:!?)\]”’])Ñ(?=[A-Za-zà-ÿ0-9(“‘\"'\s])"), "—"),
    (re.compile(r"(?<=[a-zà-ÿ])É"), "…"),
    (re.compile(r"(?<=[A-Za-zà-ÿ.,!?])Õ"), "’"),
    (re.compile(r"(?:^|(?<=[\s(\[“‘]))Ô(?=[A-Za-zà-ÿ0-9])"), "‘"),
    (re.compile(r"(?:^|(?<=[\s(\[‘]))Ò(?=[A-Za-zà-ÿ0-9])"), "“"),
    (re.compile(r"(?<=[a-zà-ÿ0-9.,!?;:)])Ó"), "”"),
    (re.compile(r"(?<=\s)Ð(?=\s)"), "–"),
    (re.compile(r"(?<=[a-zà-ÿ])Ð(?=[a-zà-ÿ])"), "–"),
)

# shortcodes
CAPTION_SHORTCODE_RE = re.compile(r"\[caption([^\]]*)\](.*?)\[/caption\]", re.S)
# a caption shortcode that fills a whole paragraph (shortcode_unautop)
CAPTION_UNAUTOP_RE = re.compile(r"<p>\s*(\[caption\b.*?\[/caption\])\s*</p>", re.S)
SHORTCODE_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
# the image (optionally linked) at the start of a caption shortcode body
CAPTION_IMAGE_RE = re.compile(r"((?:<a[^>]*>)?\s*<img[^>]*/?>\s*(?:</a>)?)", re.S)

# abstracts
ABSTRACT_LABEL_RE = re.compile(
    r"^\s*(?:<(?:b|strong|i|em|u|span|h\d)[^>]*>\s*)*"
    r"(?:summary|abstract|resumen|riassunto|r[ée]sum[ée])\s*:?\s*"
    r"(?:</(?:b|strong|i|em|u|span|h\d)>\s*)*",
    re.I,
)
EMPTY_INLINE_RE = re.compile(r"<(b|strong|i|em|u)>\s*</\1>")

# wptexturize
NO_TEXTURIZE_TAGS = ("pre", "code", "kbd", "style", "script", "tt")
# splits text into tags, shortcodes and text nodes (keeping the separators)
TEXTURIZE_SPLIT_RE = re.compile(r"(<[^>]*>|\[/?[a-zA-Z_][^\]]*\])")
TAG_NAME_RE = re.compile(r"<(/?)\s*([a-zA-Z0-9]+)")
EM_DASH_SPACED_RE = re.compile(r"(?:^|(?<=\s))--(?=$|\s)")
EN_DASH_RE = re.compile(r"(?<!xn)--")
EN_DASH_SPACED_RE = re.compile(r"(?:^|(?<=\s))-(?=$|\s)")
APOSTROPHE_YEAR_RE = re.compile(r"'(?=\d\d(?:\b|s\b))")  # '90s
OPENING_SINGLE_QUOTE_RE = re.compile(r"(?:^|(?<=[\s(\[{<\"“‘]))'(?=\S)")
OPENING_DOUBLE_QUOTE_RE = re.compile(r"(?:^|(?<=[\s(\[{<‘]))\"(?=\S)")

# wpautop: block-level elements as listed in WordPress' wpautop()
BLOCK_ELEMENTS_PATTERN = (
    r"(?:table|thead|tfoot|caption|col|colgroup|tbody|tr|td|th|div|dl|dd|dt"
    r"|ul|ol|li|pre|form|map|area|blockquote|address|style|p|h[1-6]|hr"
    r"|fieldset|legend|section|article|aside|hgroup|header|footer|nav|figure"
    r"|figcaption|details|menu|summary)"
)
DOUBLE_BR_RE = re.compile(r"<br\s*/?>\s*<br\s*/?>")
BLOCK_OPEN_TAG_RE = re.compile(r"(<" + BLOCK_ELEMENTS_PATTERN + r"[\s/>])")
BLOCK_CLOSE_TAG_RE = re.compile(r"(</" + BLOCK_ELEMENTS_PATTERN + r">)")
HR_TAG_RE = re.compile(r"(<hr\s*?/?>)")
OPTION_OPEN_RE = re.compile(r"\s*<option")
OPTION_CLOSE_RE = re.compile(r"</option>\s*")
MULTIPLE_BLANK_LINES_RE = re.compile(r"\n\n+")
PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
EMPTY_PARAGRAPH_RE = re.compile(r"<p>\s*</p>")
PARAGRAPH_IN_CONTAINER_RE = re.compile(r"<p>([^<]+)</(div|address|form)>")
PARAGRAPH_WRAPPED_BLOCK_RE = re.compile(
    r"<p>\s*(</?" + BLOCK_ELEMENTS_PATTERN + r"[^>]*>)\s*</p>"
)
PARAGRAPH_WRAPPED_LI_RE = re.compile(r"<p>(<li.+?)</p>")
PARAGRAPH_BLOCKQUOTE_RE = re.compile(r"<p><blockquote([^>]*)>", re.I)
PARAGRAPH_BEFORE_BLOCK_RE = re.compile(
    r"<p>\s*(</?" + BLOCK_ELEMENTS_PATTERN + r"[^>]*>)"
)
PARAGRAPH_AFTER_BLOCK_RE = re.compile(
    r"(</?" + BLOCK_ELEMENTS_PATTERN + r"[^>]*>)\s*</p>"
)
NEWLINE_PRESERVING_ELEMENTS_RE = re.compile(r"<(script|style|svg|math).*?</\1>", re.S)
NEWLINE_TO_BR_RE = re.compile(r"(?<!<br />)\s*\n")
BR_AFTER_BLOCK_RE = re.compile(r"(</?" + BLOCK_ELEMENTS_PATTERN + r"[^>]*>)\s*<br />")
BR_BEFORE_BLOCK_RE = re.compile(
    r"<br />(\s*</?(?:p|li|div|dl|dd|dt|th|pre|td|ul|ol)[^>]*>)"
)
TRAILING_PARAGRAPH_NEWLINE_RE = re.compile(r"\n</p>$")

# images and links
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
IMG_SRC_RE = re.compile(r'\bsrc\s*=\s*"([^"]+)"', re.I)
IMG_RESPONSIVE_ATTRS_RE = re.compile(r'\s+(?:srcset|sizes)\s*=\s*"[^"]*"', re.I)
ANCHOR_RE = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
HREF_RE = re.compile(r'\b(href)="([^"]+)"')

# --- Live site -------------------------------------------------------------

# The EJP host rejects longer/bot-like user agents with a 403
USER_AGENT = "Mozilla/5.0"
DOWNLOAD_TIMEOUT = 30
