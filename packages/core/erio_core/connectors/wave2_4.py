"""Platforms found by reading the reference site jobindex.space (second wave, batch 4).

Each reads a public, anonymous job source the platform's own career sites serve to every
visitor; how each was found, and its limits, is in docs/connectors.md.

- Homerun: the Atom feed every career site advertises in its page head
  (``https://feed.homerun.co/{tenant}``), descriptions inline.
- HR Office: career sites on the employer's own domain; ``/sitemap.xml`` lists the
  ``/vacatures/{id}-{slug}`` job pages, which carry a schema.org JobPosting.
- RecrutOr: ``https://www.recrutor.pro/{tenant}/rss/flux-rss.xml`` lists a tenant's job pages
  (the feed itself has no place or employer), each of which carries a JobPosting.
- TalentAdore: ``https://ats.talentadore.com/positions/{code}/json``, the position list a
  customer's career site embeds, descriptions inline.
- Huntflow: career sites ``{tenant}.huntflow.io`` (or ``{tenant}.global.huntflow.io``): the
  sitemap lists ``/vacancy/{slug}`` pages, which are server-rendered with their data in the
  Nuxt payload.
"""

import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from defusedxml import ElementTree

from erio_core.connectors._htmlpages import PageCrawler, listing, meta, text_of
from erio_core.connectors._service import plain
from erio_core.connectors._util import as_url, iso_datetime, join_html
from erio_core.connectors.base import Connector, Fetcher, FetchError
from erio_core.connectors.feed import parse_feed, stable_id
from erio_core.connectors.jsonld import JsonLdConnector, sitemap_locations
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
ATOM = "{http://www.w3.org/2005/Atom}"


class HomerunConnector(Connector):
    slug = "homerun"
    hosts = frozenset({"feed.homerun.co"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Homerun career site name: {board_token!r}")
        return f"https://feed.homerun.co/{board_token}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise ValueError(f"not XML: {error}") from error
        if root.tag != f"{ATOM}feed":
            raise ValueError("Homerun answers with an Atom feed")
        postings = []
        for entry in root.findall(f"{ATOM}entry"):
            link = entry.find(f"{ATOM}link")
            url = link.get("href", "") if link is not None else ""
            title = entry.findtext(f"{ATOM}title") or ""
            # The "/open" entry is the standing open-application form, not a vacancy.
            if not title.strip() or not url or url.rstrip("/").endswith("/open"):
                continue

            def name(tag: str, entry: Any = entry) -> str | None:
                return plain(entry.findtext(f"{ATOM}{tag}/{ATOM}name"))

            payload = {
                "title": title,
                "url": url,
                "company": name("author"),
                "location": name("location"),
                "department": name("department"),
                "type": name("type"),
                "salary": plain(entry.findtext(f"{ATOM}salary_indication")),
                "updated": entry.findtext(f"{ATOM}updated"),
                "description": entry.findtext(f"{ATOM}description"),
            }
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=stable_id(entry.findtext(f"{ATOM}id") or url),
                    payload=payload,
                )
            )
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("company"),
            apply_url=as_url(str(job["url"])),
            location_text=job.get("location"),
            employment_type=job.get("type"),
            description_html=job.get("description") or None,
        )


CODE = re.compile(r"[A-Za-z0-9]{1,20}")


class TalentAdoreConnector(Connector):
    """TalentAdore position lists. The board token is the list's code, from the
    ``/positions/{code}/json`` address a customer's career site loads."""

    slug = "talentadore"
    hosts = frozenset({"ats.talentadore.com"})

    def board_url(self, board_token: str) -> str:
        if not CODE.fullmatch(board_token):
            raise ValueError(f"not a TalentAdore position list code: {board_token!r}")
        return f"https://ats.talentadore.com/positions/{board_token}/json"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        postings = []
        for job in data["jobs"]:
            ref = job.get("job_token")
            if not ref or not job.get("name") or not job.get("link"):
                continue
            payload = {k: v for k, v in job.items() if k not in ("id", "job_token")}
            payload["ref"] = ref
            payload["company"] = plain(data.get("company"))
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=str(ref),
                    payload=payload,
                )
            )
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        # Customers fill "location" with a street address: the city or county names the place.
        place = [plain(job.get(key)) for key in ("city", "county", "country")]
        text = ", ".join(p for p in place if p) or plain(job.get("location"))
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["name"]).strip(),
            company_name=plain(job.get("business_unit_name")) or job.get("company"),
            apply_url=as_url(str(job["link"])),
            posted_at=iso_datetime(job.get("start_date")),
            location_text=text,
            city=plain(job.get("city")) or plain(job.get("county")),
            employment_type=plain(job.get("employment_type")),
            description_html=job.get("description_html") or None,
        )


HUNTFLOW_TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}(?:\.global)?")
NUXT_DATA = re.compile(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
NUXT_WRAPPERS = frozenset({"ShallowReactive", "Reactive", "Ref", "ShallowRef"})


def nuxt_value(data: list[Any], index: int, depth: int = 0) -> Any:
    """One value of a Nuxt payload: an array whose items refer to each other by position."""
    if depth > 12:
        return None
    item = data[index]
    if isinstance(item, list):
        if len(item) == 2 and item[0] in NUXT_WRAPPERS:
            return nuxt_value(data, item[1], depth + 1)
        return [nuxt_value(data, i, depth + 1) for i in item if isinstance(i, int)]
    if isinstance(item, dict):
        return {k: nuxt_value(data, v, depth + 1) for k, v in item.items() if isinstance(v, int)}
    return item


class HuntflowConnector(PageCrawler):
    """Huntflow career sites. The board token is the site's name, "{tenant}" for
    ``{tenant}.huntflow.io`` or "{tenant}.global" for ``{tenant}.global.huntflow.io``."""

    slug = "huntflow"
    hosts = frozenset({"*.huntflow.io", "*.global.huntflow.io"})

    def _host(self, board_token: str) -> str:
        if not HUNTFLOW_TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Huntflow career site name: {board_token!r}")
        return f"{board_token}.huntflow.io"

    def board_url(self, board_token: str) -> str:
        return f"https://{self._host(board_token)}/sitemap.xml"

    def job_urls(self, fetcher: Fetcher, board_token: str) -> list[str]:
        host = self._host(board_token)
        try:
            pages, _ = sitemap_locations(listing(fetcher, self.board_url(board_token)))
        except ElementTree.ParseError as error:
            raise FetchError("parse_error", f"malformed sitemap: {error}", 200) from error
        wanted = re.compile(rf"https://{re.escape(host)}/vacancy/[a-z0-9._~-]+")
        return [u for u in dict.fromkeys(pages) if wanted.fullmatch(u)]

    def item_id(self, url: str, page: dict[str, Any]) -> str:
        return str(page["id"])

    def read_page(self, url: str, body: bytes) -> dict[str, Any] | None:
        html = body.decode("utf-8", "replace")
        found = NUXT_DATA.search(html)
        if not found:
            return None
        root = nuxt_value(json.loads(found.group(1)), 0)
        fetched = root["data"] if isinstance(root, dict) else {}
        job = next((v for v in fetched.values() if isinstance(v, dict) and v.get("position")), None)
        if not job or job.get("is_archived") or job.get("archived_at"):
            return None
        site = meta(html, "og:site_name") or ""
        company = site.removesuffix(" Job Openings") if site.endswith(" Job Openings") else None
        return {
            "id": job["id"],
            "title": job["position"],
            "company": company,
            "city": job.get("city"),
            "division": job.get("division"),
            "money": job.get("money"),
            "sections": [job.get(k) for k in ("intro", "body", "conditions", "requirements")],
        }

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        money = plain(job.get("money"))
        parts = [f"<p>{money}</p>" if money else None, *job.get("sections", [])]
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=text_of(str(job["title"])),
            company_name=plain(job.get("company")),
            apply_url=as_url(str(job["url"])),
            location_text=plain(job.get("city")),
            description_html=join_html(*parts),
        )


class RecrutorConnector(JsonLdConnector):
    """RecrutOr career spaces (``www.recrutor.pro/{tenant}/``). The board token is the tenant."""

    def __init__(self) -> None:
        super().__init__("recrutor", r"^/[a-z0-9-]+/emploi-", frozenset({"www.recrutor.pro"}))

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a RecrutOr career space name: {board_token!r}")
        return f"https://www.recrutor.pro/{board_token}/rss/flux-rss.xml"

    def job_pages(self, fetcher: Fetcher, board_token: str) -> list[str]:
        response = fetcher.get(self.board_url(board_token))
        if response.status != 200:
            raise FetchError("http_error", f"HTTP {response.status}", response.status)
        try:
            jobs = parse_feed(response.body)
        except ValueError as error:
            raise FetchError("parse_error", f"malformed feed: {error}", 200) from error
        pages = []
        for job in jobs:
            parts = urlsplit(str(job["url"]))
            if parts.hostname == "www.recrutor.pro" and self.job_path.search(parts.path):
                pages.append(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))
        return list(dict.fromkeys(pages))


WAVE2_4_CONNECTORS: list[Connector] = [
    HomerunConnector(),
    # "/vacatures/{id}-{slug}/solliciteren" is the application form, not the job.
    JsonLdConnector("hroffice", r"^/vacatures/\d+-[^/]+$"),
    RecrutorConnector(),
    TalentAdoreConnector(),
    HuntflowConnector(),
]
