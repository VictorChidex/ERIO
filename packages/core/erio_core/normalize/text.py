"""Clean titles and descriptions (spec sections 6 and 9).

Titles lose noise (emoji, "URGENT", requisition IDs, gender tags) but keep
seniority words. Descriptions are sanitized to an allow-list of tags before
storage, and a plain-text copy is kept for search.
"""

import html
import re

import nh3

EMOJI = re.compile(
    "[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u200d]+", flags=re.UNICODE
)
NOISE_WORDS = re.compile(
    r"\b(urgent(?:ly)?|hiring now|immediate (?:start|joiner)|apply now|new!?)\b[!:]*",
    re.IGNORECASE,
)
REQUISITION = re.compile(
    r"\s*(?:[(\[]\s*(?:req(?:uisition)?\.?\s*(?:id)?[:#\s-]*)?[A-Z]{0,4}-?\d{4,}\s*[)\]]"
    r"|\b(?:req(?:uisition)?\.?\s*(?:id)?|job id|ref)[:#\s-]*[A-Z]{0,4}-?\d{3,}\b"
    r"|\s#\d{4,}\b|\s-\s[A-Z]{1,3}\d{5,}\b)",
    re.IGNORECASE,
)
GENDER_TAG = re.compile(r"\(\s*[mwfdxh]\s*/\s*[mwfdxh]\s*(?:/\s*[mwfdxh]\s*)?\)", re.IGNORECASE)

ALLOWED_TAGS = {
    "p", "br", "ul", "ol", "li", "strong", "b", "em", "i", "u", "h2", "h3", "h4", "h5",
    "blockquote", "a", "span", "div", "table", "thead", "tbody", "tr", "th", "td",
}  # fmt: skip
ALLOWED_ATTRIBUTES = {"a": {"href"}}


def clean_title(title: str) -> str:
    text = EMOJI.sub(" ", title)
    text = GENDER_TAG.sub(" ", text)
    text = REQUISITION.sub(" ", text)
    text = NOISE_WORDS.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^[\s\-–—|:,!*]+|[\s\-–—|:,!*]+$", "", text)
    text = re.sub(r"\(\s*\)|\[\s*\]", "", text).strip()
    return text or title.strip()


def sanitize_html(content: str) -> str:
    """Description HTML reduced to an allow-list of tags; links get rel=noopener."""
    return nh3.clean(
        content,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"https", "http", "mailto"},
        link_rel="noopener noreferrer nofollow",
    )


BLOCK_TAG = re.compile(r"<(/?)(p|br|li|div|h\d|tr|td|th|ul|ol|blockquote)\b", re.IGNORECASE)


def html_to_text(content: str) -> str:
    # Block tags separate words: "<p>ship</p><li>Go" is "ship Go", not "shipGo".
    text = nh3.clean(BLOCK_TAG.sub(r" <\1\2", content), tags=set())
    return re.sub(r"\s+", " ", html.unescape(text)).strip()
