"""Formatting of WordPress post text.

Post text is stored in the export the way WordPress keeps it in the
database: paragraphs separated by blank lines, straight quotes and dashes.
WordPress only formats it at render time (``wpautop``/``wptexturize``),
so equivalent formatting is applied here before the HTML galley is saved.
"""

import html

from .consts import (
    ABSTRACT_LABEL_RE,
    APOSTROPHE_YEAR_RE,
    BLOCK_CLOSE_TAG_RE,
    BLOCK_OPEN_TAG_RE,
    BR_AFTER_BLOCK_RE,
    BR_BEFORE_BLOCK_RE,
    CAPTION_IMAGE_RE,
    CAPTION_SHORTCODE_RE,
    CAPTION_UNAUTOP_RE,
    DOUBLE_BR_RE,
    EM_DASH_SPACED_RE,
    EMPTY_INLINE_RE,
    EMPTY_PARAGRAPH_RE,
    EN_DASH_RE,
    EN_DASH_SPACED_RE,
    HR_TAG_RE,
    HTML_TAG_RE,
    MOJIBAKE_RULES,
    MULTIPLE_BLANK_LINES_RE,
    NEWLINE_PRESERVING_ELEMENTS_RE,
    NEWLINE_TO_BR_RE,
    NO_TEXTURIZE_TAGS,
    OPENING_DOUBLE_QUOTE_RE,
    OPENING_SINGLE_QUOTE_RE,
    OPTION_CLOSE_RE,
    OPTION_OPEN_RE,
    PARAGRAPH_AFTER_BLOCK_RE,
    PARAGRAPH_BEFORE_BLOCK_RE,
    PARAGRAPH_BLOCKQUOTE_RE,
    PARAGRAPH_IN_CONTAINER_RE,
    PARAGRAPH_SPLIT_RE,
    PARAGRAPH_WRAPPED_BLOCK_RE,
    PARAGRAPH_WRAPPED_LI_RE,
    SHORTCODE_ATTR_RE,
    TAG_NAME_RE,
    TEXTURIZE_SPLIT_RE,
    TRAILING_PARAGRAPH_NEWLINE_RE,
    WHITESPACE_RE,
)


def strip_tags(text):
    """Plain text of an HTML fragment, whitespace collapsed."""
    return WHITESPACE_RE.sub(
        " ", html.unescape(HTML_TAG_RE.sub(" ", text or ""))
    ).strip()


def fix_mojibake(text):
    """Undo Mac Roman punctuation that was decoded as Latin-1."""
    if not text:
        return text
    for pattern, replacement in MOJIBAKE_RULES:
        text = pattern.sub(replacement, text)
    return text


def expand_caption_shortcode(match):
    attrs = dict(SHORTCODE_ATTR_RE.findall(match.group(1)))
    inner = match.group(2).strip()
    image_match = CAPTION_IMAGE_RE.match(inner)
    if image_match:
        image = image_match.group(1).strip()
        caption = inner[image_match.end() :].strip()
    else:
        image, caption = inner, ""
    caption = caption or attrs.get("caption", "")
    return (
        '<figure class="wp-caption {align}">{image}'
        '<figcaption class="wp-caption-text">{caption}</figcaption></figure>'
    ).format(align=attrs.get("align", "alignnone"), image=image, caption=caption)


def expand_shortcodes(text):
    """Render the WordPress shortcodes found in the export as HTML.

    Like WordPress, this runs after wpautop(): a shortcode that fills a
    whole paragraph is first unwrapped from its <p> (shortcode_unautop).
    """
    text = CAPTION_UNAUTOP_RE.sub(r"\1", text)
    return CAPTION_SHORTCODE_RE.sub(expand_caption_shortcode, text)


def texturize_fragment(text):
    """Port of the wptexturize replacements used on plain text."""
    text = text.replace("...", "…").replace("``", "“").replace("''", "”")
    text = text.replace("---", "—")
    text = EM_DASH_SPACED_RE.sub("—", text)
    text = EN_DASH_RE.sub("–", text)
    text = EN_DASH_SPACED_RE.sub("–", text)
    # apostrophes and single quotes
    text = APOSTROPHE_YEAR_RE.sub("’", text)
    text = OPENING_SINGLE_QUOTE_RE.sub("‘", text)
    text = text.replace("'", "’")
    # double quotes
    text = OPENING_DOUBLE_QUOTE_RE.sub("“", text)
    text = text.replace('"', "”")
    return text


def wptexturize(text):
    """Convert straight quotes, dashes and ellipses in text nodes only."""
    if not text:
        return text
    output = []
    skip_depth = 0
    for part in TEXTURIZE_SPLIT_RE.split(text):
        if part.startswith("<"):
            tag = TAG_NAME_RE.match(part)
            if tag and tag.group(2).lower() in NO_TEXTURIZE_TAGS:
                skip_depth = max(0, skip_depth + (-1 if tag.group(1) else 1))
            output.append(part)
        elif part.startswith("[") or skip_depth or not part:
            output.append(part)
        else:
            output.append(texturize_fragment(part))
    return "".join(output)


def wpautop(text, br=True):
    """Port of WordPress' wpautop(): blank lines become paragraphs and
    single newlines become <br /> tags, without touching block elements."""
    if not text or not text.strip():
        return ""
    pre_tags = {}
    text = text + "\n"

    if "<pre" in text:
        pieces = text.split("</pre>")
        last = pieces.pop()
        text = ""
        for index, piece in enumerate(pieces):
            start = piece.find("<pre")
            if start == -1:
                text += piece
                continue
            name = "<pre wp-pre-tag-{}></pre>".format(index)
            pre_tags[name] = piece[start:] + "</pre>"
            text += piece[:start] + name
        text += last

    text = DOUBLE_BR_RE.sub("\n\n", text)
    text = BLOCK_OPEN_TAG_RE.sub(r"\n\n\1", text)
    text = BLOCK_CLOSE_TAG_RE.sub(r"\1\n\n", text)
    text = HR_TAG_RE.sub(r"\1\n\n", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # newlines inside tags must not be treated as line breaks
    text = HTML_TAG_RE.sub(lambda m: m.group().replace("\n", " <!-- wpnl --> "), text)
    if "<option" in text:
        text = OPTION_OPEN_RE.sub("<option", text)
        text = OPTION_CLOSE_RE.sub("</option>", text)
    text = MULTIPLE_BLANK_LINES_RE.sub("\n\n", text)

    paragraphs = [p for p in PARAGRAPH_SPLIT_RE.split(text) if p]
    text = "".join("<p>{}</p>\n".format(p.strip("\n")) for p in paragraphs)

    text = EMPTY_PARAGRAPH_RE.sub("", text)
    text = PARAGRAPH_IN_CONTAINER_RE.sub(r"<p>\1</p></\2>", text)
    text = PARAGRAPH_WRAPPED_BLOCK_RE.sub(r"\1", text)
    text = PARAGRAPH_WRAPPED_LI_RE.sub(r"\1", text)
    text = PARAGRAPH_BLOCKQUOTE_RE.sub(r"<blockquote\1><p>", text)
    text = text.replace("</blockquote></p>", "</p></blockquote>")
    text = PARAGRAPH_BEFORE_BLOCK_RE.sub(r"\1", text)
    text = PARAGRAPH_AFTER_BLOCK_RE.sub(r"\1", text)

    if br:
        text = NEWLINE_PRESERVING_ELEMENTS_RE.sub(
            lambda m: m.group().replace("\n", "<WPPreserveNewline />"), text
        )
        text = text.replace("<br>", "<br />").replace("<br/>", "<br />")
        text = NEWLINE_TO_BR_RE.sub("<br />\n", text)
        text = text.replace("<WPPreserveNewline />", "\n")

    text = BR_AFTER_BLOCK_RE.sub(r"\1", text)
    text = BR_BEFORE_BLOCK_RE.sub(r"\1", text)
    text = TRAILING_PARAGRAPH_NEWLINE_RE.sub("</p>", text)

    for name, original in pre_tags.items():
        text = text.replace(name, original)
    text = text.replace(" <!-- wpnl --> ", "\n").replace("<!-- wpnl -->", "\n")
    return text


def format_wp_html(text):
    """Turn raw WordPress post text into the HTML the site would render."""
    if not text or not text.strip():
        return ""
    text = fix_mojibake(text)
    text = wptexturize(text)
    text = wpautop(text)
    return expand_shortcodes(text).strip()


def format_abstract(text):
    """Strip a leading "Summary:"/"Abstract:" label and format the rest."""
    text = EMPTY_INLINE_RE.sub("", text or "")
    text = ABSTRACT_LABEL_RE.sub("", text)
    return format_wp_html(text)
