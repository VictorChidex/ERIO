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
"""

import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from defusedxml import ElementTree

from erio_core.connectors._service import plain
from erio_core.connectors._util import as_url, iso_datetime
from erio_core.connectors.base import Connector, Fetcher, FetchError
from erio_core.connectors.feed import parse_feed, stable_id
from erio_core.connectors.jsonld import JsonLdConnector
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
]
