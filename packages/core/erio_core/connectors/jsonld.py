"""schema.org JobPosting pages: the structured data Google for Jobs reads.

Most career sites and job boards mark each job page up with a JobPosting in
a ``<script type="application/ld+json">`` block, so this connector serves
any platform that does, however its pages look. The board token is a full
https URL: a sitemap (``.xml``), whose ``<loc>`` entries are the job pages,
or a listing page, whose same-site links matching the platform's job-page
pattern are. Each job page is then fetched and its JobPosting read.

A crawl fetches at most ``max_pages`` job pages, one by one through the
polite fetcher, so a large board is covered over several crawls.
"""

import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

from defusedxml import ElementTree
from pydantic import HttpUrl

from erio_core.connectors._util import iso_datetime, salary
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.connectors.feed import stable_id
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

SCRIPT = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
MAX_PAGES = 200
MAX_SITEMAPS = 5


def _walk(node: Any) -> list[dict[str, Any]]:
    """Every object whose @type is (or includes) JobPosting, at any depth."""
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            found += _walk(item)
    elif isinstance(node, dict):
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "JobPosting" in kinds:
            found.append(node)
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in node:
                found += _walk(node[key])
    return found


def job_postings(html: str) -> list[dict[str, Any]]:
    """The JobPosting objects in a page's JSON-LD blocks (malformed blocks skipped)."""
    postings: list[dict[str, Any]] = []
    for block in SCRIPT.findall(html):
        try:
            postings += _walk(json.loads(block.strip()))
        except json.JSONDecodeError:
            continue
    return postings


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.hrefs += [value for name, value in attrs if name == "href" and value]


def page_links(html: str, base: str, pattern: re.Pattern[str]) -> list[str]:
    """Same-host links on a listing page whose path matches the job-page pattern."""
    reader = _Links()
    reader.feed(html)
    host = urlsplit(base).hostname
    links = []
    for href in reader.hrefs:
        url = urljoin(base, href).split("#", 1)[0]
        parts = urlsplit(url)
        if parts.scheme == "https" and parts.hostname == host and pattern.search(parts.path):
            links.append(url)
    return list(dict.fromkeys(links))


def sitemap_locations(body: bytes) -> tuple[list[str], list[str]]:
    """(page URLs, nested sitemap URLs) from a sitemap or sitemap index."""
    root = ElementTree.fromstring(body)
    locations = [
        (element.text or "").strip() for element in root.iter() if element.tag.endswith("loc")
    ]
    if root.tag.endswith("sitemapindex"):
        return [], locations
    return locations, []


def _text(value: Any) -> str | None:
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("@id"))
    if isinstance(value, list):
        return _text(value[0]) if value else None
    return str(value).strip() or None if value is not None else None


def _places(posting: dict[str, Any]) -> list[dict[str, Any]]:
    places = posting.get("jobLocation") or []
    places = places if isinstance(places, list) else [places]
    return [p.get("address") or {} for p in places if isinstance(p, dict)]


def _location_text(address: dict[str, Any] | str) -> str | None:
    if isinstance(address, str):
        return address.strip() or None
    parts = [
        _text(address.get(key)) for key in ("addressLocality", "addressRegion", "addressCountry")
    ]
    return ", ".join(p for p in parts if p) or None


def parse_job_posting(
    slug: str, external_id: str, page_url: str, posting: dict[str, Any]
) -> PartialJob:
    """A JobPosting object as ERIO reads it."""
    addresses = _places(posting)
    first = addresses[0] if addresses else {}
    first = first if isinstance(first, dict) else {}
    remote = str(posting.get("jobLocationType") or "").upper() == "TELECOMMUTE"
    workplace: RemoteStatus | None = "remote" if remote else None
    pay = posting.get("baseSalary") or {}
    pay = pay if isinstance(pay, dict) else {}
    value: dict[str, Any] = pay["value"] if isinstance(pay.get("value"), dict) else {}
    kinds = posting.get("employmentType") or []
    kinds = kinds if isinstance(kinds, list) else [kinds]
    locations = [text for a in addresses if (text := _location_text(a))]
    if not locations and remote:
        locations = [
            f"Remote, {name}"
            for req in (posting.get("applicantLocationRequirements") or [])
            if isinstance(req, dict) and (name := _text(req.get("name")))
        ] or ["Remote"]
    return PartialJob(
        source_slug=slug,
        external_id=external_id,
        title=str(posting["title"]).strip(),
        company_name=_text(posting.get("hiringOrganization")),
        apply_url=HttpUrl(_text(posting.get("url")) or page_url),
        posted_at=_date(posting.get("datePosted")),
        location_text="; ".join(dict.fromkeys(locations)) or None,
        city=_text(first.get("addressLocality")),
        region=_text(first.get("addressRegion")),
        country_hint=_text(first.get("addressCountry")),
        workplace_type=workplace,
        employment_type=", ".join(str(k) for k in kinds if k) or None,
        salary=salary(
            value.get("minValue") or value.get("value"),
            value.get("maxValue"),
            pay.get("currency"),
            value.get("unitText") or pay.get("unitText"),
        ),
        description_html=_text(posting.get("description")),
    )


def _date(value: Any) -> Any:
    try:
        return iso_datetime(value)
    except ValueError:
        return None


class JsonLdConnector(Connector):
    """One platform whose job pages carry JobPosting data. ``job_path`` is
    the pattern a link's path must match to be a job page (listing pages
    link to many other things)."""

    def __init__(
        self,
        slug: str,
        job_path: str,
        hosts: frozenset[str] = frozenset(),
        max_pages: int = MAX_PAGES,
    ):
        self.slug = slug
        self.hosts = hosts
        self.job_path = re.compile(job_path)
        self.max_pages = max_pages

    def board_url(self, board_token: str) -> str:
        if not board_token.startswith("https://"):
            raise ValueError(f"{self.slug}: the board token must be an https URL")
        return board_token

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        """The JobPostings on one job page (the board token is that page)."""
        return self._postings(body.decode("utf-8", "replace"), board_token)

    def _postings(self, html: str, page_url: str) -> list[RawPosting]:
        postings = []
        for posting in job_postings(html):
            if not posting.get("title"):
                continue
            ident = _text(posting.get("identifier")) or page_url
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=page_url,
                    external_id=stable_id(f"{page_url}#{ident}"),
                    payload={"page_url": page_url, "posting": posting},
                )
            )
        return postings[:1]

    def job_pages(self, fetcher: Fetcher, board_token: str) -> list[str]:
        response = fetcher.get(self.board_url(board_token))
        if response.status != 200:
            raise FetchError("http_error", f"HTTP {response.status}", response.status)
        if board_token.endswith(".xml") or response.body.lstrip().startswith(b"<?xml"):
            try:
                pages, nested = sitemap_locations(response.body)
                for url in nested[:MAX_SITEMAPS]:
                    more = fetcher.get(url)
                    if more.status == 200:
                        pages += sitemap_locations(more.body)[0]
            except ElementTree.ParseError as error:
                raise FetchError("parse_error", f"malformed sitemap: {error}", 200) from error
            return [p for p in dict.fromkeys(pages) if self.job_path.search(urlsplit(p).path)]
        return page_links(response.body.decode("utf-8", "replace"), board_token, self.job_path)

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        pages = self.job_pages(fetcher, board_token)
        postings: list[RawPosting] = []
        for url in pages[: self.max_pages]:
            try:
                response = fetcher.get(url)
            except FetchError:
                continue  # one unreachable job page does not fail the board
            if response.status == 200:
                found = self._postings(response.body.decode("utf-8", "replace"), url)
                postings += [p.model_copy(update={"board_token": board_token}) for p in found]
        if pages and not postings:
            raise FetchError("parse_error", "job pages carry no JobPosting data", 200)
        return BoardFetch(postings=postings, http_status=200, body=b"")

    def parse(self, raw: RawPosting) -> PartialJob:
        payload = raw.payload
        return parse_job_posting(
            self.slug, raw.external_id, str(payload["page_url"]), payload["posting"]
        )
