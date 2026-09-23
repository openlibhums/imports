"""Helpers for reading the items of a WordPress WXR export: elements,
postmeta, authors, dates and the order in which posts are listed."""

import html
from datetime import datetime
from urllib.parse import urlsplit

from django.utils import timezone

from .consts import (
    AUTHOR_SPLIT_RE,
    CURLY_DOUBLE_QUOTES_RE,
    CURLY_SINGLE_QUOTES_RE,
    DATE_PUNCTUATION_RE,
    DAY_MONTH_YEAR_RE,
    FRONT_MATTER_RE,
    MONTH_DAY_YEAR_RE,
    MONTH_YEAR_RE,
    MONTHS,
    NS,
    NUMERIC_DATE_RE,
    ORDINAL_SUFFIX_RE,
    RELEASE_MONTH_YEAR_RE,
    SEASON_MONTHS,
    SEASON_RE,
    SPANISH_DE_RE,
    WHITESPACE_RE,
    WP_DATE_FORMAT,
    YEAR_RE,
)
from .text import fix_mojibake, format_wp_html, strip_tags

# --- Elements and postmeta -------------------------------------------------


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


def category_slugs(item):
    return [
        cat.get("nicename")
        for cat in item.findall("category")
        if cat.get("domain") == "category" and cat.get("nicename")
    ]


def build_body_html(meta):
    """Assemble the article body from the text and blocks_* postmeta."""
    parts = []
    if meta.get("text"):
        parts.append(format_wp_html(meta["text"]))
    index = 0
    while True:
        text = meta.get("blocks_{}_text".format(index))
        title = meta.get("blocks_{}_title".format(index))
        if text is None and title is None:
            break
        if title and title.strip():
            parts.append("<h2>{}</h2>".format(fix_mojibake(title.strip())))
        if text:
            parts.append(format_wp_html(text))
        index += 1
    return "\n".join(part for part in parts if part).strip()


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


# --- Authors ---------------------------------------------------------------


def split_authors(raw):
    """Split a free-text author string into individual names."""
    raw = WHITESPACE_RE.sub(" ", html.unescape(raw or "")).strip()
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


# --- Dates -----------------------------------------------------------------


def make_aware(naive):
    return timezone.make_aware(naive, timezone.get_current_timezone())


def parse_date(meta_date):
    """Parse a WP '2021-10-10 11:36:17' date into an aware datetime."""
    if not meta_date or meta_date.startswith("0000"):
        return None
    try:
        parsed = datetime.strptime(meta_date, WP_DATE_FORMAT)
    except ValueError:
        return None
    return make_aware(parsed)


def parse_release_date(raw):
    """Parse an issue's free-text release date ("2021", "Spring-Summer 1995",
    "February 2020 - May 2020", "1995-2026").

    Returns (aware datetime or None, sorted list of the years mentioned).
    """
    text = html.unescape(raw or "").lower()
    years = sorted({int(y) for y in YEAR_RE.findall(text)})
    if not years:
        return None, []
    year, month = years[0], 1
    month_match = RELEASE_MONTH_YEAR_RE.search(text)
    season_match = SEASON_RE.search(text)
    if month_match:
        month, year = MONTHS[month_match.group(1)], int(month_match.group(2))
    elif season_match:
        month = SEASON_MONTHS[season_match.group(1)]
    return make_aware(datetime(year, month, 1)), years


def parse_block_date(raw, hint=None):
    """Parse the publication date block ("November 12, 2021", "12/03/2021",
    "9 de febrero, 2022", "Marzo 2022"). ``hint`` disambiguates numeric
    day/month order by picking the reading closest to the WP post date."""
    text = strip_tags(raw).lower()
    text = ORDINAL_SUFFIX_RE.sub(r"\1", text)
    text = SPANISH_DE_RE.sub(" ", text)
    text = DATE_PUNCTUATION_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return None

    numeric = NUMERIC_DATE_RE.match(text)
    if numeric:
        first, second, year = (int(g) for g in numeric.groups())
        candidates = []
        for day, month in ((first, second), (second, first)):
            try:
                candidates.append(datetime(year, month, day))
            except ValueError:
                continue
        if not candidates:
            return None
        if hint and len(candidates) > 1:
            naive_hint = hint.replace(tzinfo=None)
            candidates.sort(key=lambda c: abs((c - naive_hint).total_seconds()))
        return make_aware(candidates[0])

    for pattern, order in (
        (MONTH_DAY_YEAR_RE, ("month", "day", "year")),
        (DAY_MONTH_YEAR_RE, ("day", "month", "year")),
        (MONTH_YEAR_RE, ("month", "year")),
    ):
        match = pattern.match(text)
        if not match:
            continue
        values = dict(zip(order, match.groups()))
        try:
            return make_aware(
                datetime(
                    int(values["year"]),
                    MONTHS[values["month"]],
                    int(values.get("day", 1)),
                )
            )
        except (ValueError, KeyError):
            return None
    return None


# --- Article ordering ------------------------------------------------------


def link_key(url):
    """Normalise a WP permalink so live pages and export items can be matched."""
    return urlsplit(url.strip()).path.strip("/").lower()


def normalise_title(title):
    title = html.unescape(title or "").lower()
    title = CURLY_DOUBLE_QUOTES_RE.sub('"', CURLY_SINGLE_QUOTES_RE.sub("'", title))
    return WHITESPACE_RE.sub(" ", title).strip()


def title_key(item):
    return normalise_title(element_text(item, "title"))


def is_subpost(item):
    return item is not None and collect_postmeta(item).get("subpost", "").strip() == "1"


def group_subposts(entries):
    """Move sub-posts (e.g. "Idiom: ...") right after the article they
    extend, mirroring how the WordPress theme nests them. The parent is
    the article whose title (up to its first colon) prefixes the sub-post's
    title. Sub-posts without a parent stay where they are."""
    parents = []
    for article, item in entries:
        if item is None or is_subpost(item):
            continue
        key = title_key(item).split(":")[0].strip()
        if len(key) >= 4:
            parents.append((key, article.pk))

    attached = {}
    remaining = []
    for article, item in entries:
        parent_pk = None
        if is_subpost(item):
            title = title_key(item)
            best = ""
            for key, pk in parents:
                if (
                    len(key) > len(best)
                    and title.startswith(key)
                    and (len(title) == len(key) or not title[len(key)].isalnum())
                ):
                    best, parent_pk = key, pk
        if parent_pk is None:
            remaining.append((article, item))
        else:
            attached.setdefault(parent_pk, []).append((article, item))

    ordered = []
    for article, item in remaining:
        ordered.append((article, item))
        children = attached.get(article.pk, [])
        children.sort(key=lambda entry: element_text(entry[1], "wp:post_date"))
        ordered.extend(children)
    return ordered


def fallback_order(entries):
    """Order (article, wp item) pairs the way WordPress lists posts when no
    manual order is known: newest first, with front matter (table of
    contents, contributors) at the top and sub-posts under their parent."""

    def sort_key(entry):
        article, item = entry
        if item is None:
            return (2, "", article.title or "")
        is_front = bool(FRONT_MATTER_RE.match(title_key(item)))
        # negative timestamp-ish key: reverse the date string
        date = element_text(item, "wp:post_date")
        reversed_date = "".join(chr(0x10FFFF - ord(c)) for c in date)
        return (0 if is_front else 1, reversed_date, article.title or "")

    return group_subposts(sorted(entries, key=sort_key))
