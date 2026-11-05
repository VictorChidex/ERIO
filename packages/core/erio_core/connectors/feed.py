"""Job feeds: RSS 2.0, Atom, and the Indeed-style XML job feed.

Many job-board products and some applicant tracking systems publish every
open job in one feed, so one connector serves them all. Each platform gets
its own instance (and source) with the hosts it uses and, where the board
token is not already a full URL, the feed URL to build from it.

Items become payloads with the same keys whatever the format: id, title,
url, description, published, location, company, employment_type, salary,
remote. XML is parsed with defusedxml, so a hostile feed cannot expand
entities or reach out to other hosts.
"""

import hashlib
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from erio_core.connectors._util import iso_datetime
from erio_core.connectors.base import Connector
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
REMOTE_WORDS = ("remote", "anywhere", "work from home", "telecommute")


def _local(tag: str) -> str:
    """Tag name without its namespace: "{ns}location" is "location"."""
    return tag.rsplit("}", 1)[-1].lower()


def _children(element: Element) -> dict[str, str]:
    """Text of each child element by local name (first one wins)."""
    found: dict[str, str] = {}
    for child in element:
        text = (child.text or "").strip()
        if text:
            found.setdefault(_local(child.tag), text)
        elif _local(child.tag) == "link" and child.get("href"):
            found.setdefault("link", child.get("href", ""))
    return found


def _location(fields: dict[str, str]) -> str | None:
    if fields.get("location"):
        return fields["location"]
    parts = [fields.get(k) for k in ("city", "state", "region", "country")]
    return ", ".join(p for p in parts if p) or None


def _item(fields: dict[str, str], description: str | None) -> dict[str, Any]:
    url = fields.get("url") or fields.get("link") or fields.get("applyurl")
    return {
        "id": fields.get("guid") or fields.get("referencenumber") or fields.get("id") or url,
        "title": fields.get("title"),
        "url": url,
        "description": description,
        "published": fields.get("pubdate") or fields.get("published") or fields.get("date")
        or fields.get("updated"),
        "location": _location(fields),
        "company": fields.get("company") or fields.get("author"),
        "employment_type": fields.get("jobtype") or fields.get("employmenttype")
        or fields.get("type"),
        "salary": fields.get("salary"),
        "remote": fields.get("remotetype") or fields.get("remote"),
    }  # fmt: skip


def parse_feed(body: bytes) -> list[dict[str, Any]]:
    """Every job in an RSS, Atom or Indeed-style XML feed; ValueError if it is none."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise ValueError(f"not XML: {error}") from error
    tag = _local(root.tag)
    if tag == "rss":
        items = root.findall("./channel/item")
        descriptions = [i.findtext(CONTENT) or i.findtext("description") for i in items]
    elif tag == "feed":
        items = root.findall(f"{ATOM}entry")
        descriptions = [i.findtext(f"{ATOM}content") or i.findtext(f"{ATOM}summary") for i in items]
    elif tag in ("source", "jobs"):
        items = [e for e in root if _local(e.tag) == "job"]
        descriptions = [_children(i).get("description") for i in items]
    else:
        raise ValueError(f"not a job feed: <{tag}>")
    jobs = [_item(_children(i), d) for i, d in zip(items, descriptions, strict=True)]
    return [job for job in jobs if job["title"] and job["url"]]


def feed_date(value: Any) -> datetime | None:
    """RSS dates are RFC 822 ("Tue, 04 Nov 2026 10:00:00 GMT"), Atom's ISO 8601."""
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))
    except (TypeError, ValueError):
        try:
            return iso_datetime(value)
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def stable_id(value: str) -> str:
    """Short stable ID for a job that only has a URL."""
    return hashlib.sha256(value.encode()).hexdigest()[:24]


class FeedConnector(Connector):
    """One platform's job feeds. ``feed_url`` builds the URL from a short
    token; a token that is already a full https URL is used as it is (and its
    host is allowed because the board is registered)."""

    def __init__(self, slug: str, hosts: frozenset[str] = frozenset(), feed_url: str | None = None):
        self.slug = slug
        self.hosts = hosts
        self.feed_url = feed_url

    def board_url(self, board_token: str) -> str:
        if board_token.startswith("https://"):
            return board_token
        if self.feed_url is None or not board_token.replace("-", "").isalnum():
            raise ValueError(f"{self.slug}: a feed board token must be an https URL")
        return self.feed_url.format(token=board_token)

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=stable_id(str(job["id"])),
                payload=job,
            )
            for job in parse_feed(body)
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        flags = f"{job.get('remote') or ''} {job.get('location') or ''}".lower()
        workplace: RemoteStatus | None = (
            "remote" if any(word in flags for word in REMOTE_WORDS) else None
        )
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("company"),
            apply_url=job["url"],
            posted_at=feed_date(job.get("published")),
            location_text=job.get("location"),
            workplace_type=workplace,
            employment_type=job.get("employment_type"),
            description_html=job.get("description"),
        )
