"""Platforms of connector wave 2/3, found by reading the reference index
(docs/reference-sources-jobindex.md). Each reads a public, unauthenticated surface that the
platform's own sites serve to every visitor; how each was found, and its limits, is in
docs/connectors.md.

- Crelate: the RSS feed behind every candidate portal (``/portal/{org}/rss``).
- GeekJob: server-rendered ``/vacancies/{n}`` lists; every vacancy page carries JobPosting data.
- Beehire: the JSON behind every career page (``/users/getPublicCampaigns/{name}``).
"""

import json
import re
from typing import Any

from erio_core.connectors._util import as_url
from erio_core.connectors.base import Connector, Fetcher, FetchError
from erio_core.connectors.feed import feed_date, stable_id, xml_items
from erio_core.connectors.jsonld import JsonLdConnector, page_links
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")


# ---------------------------------------------------------------- Crelate


class CrelateConnector(Connector):
    slug = "crelate"
    hosts = frozenset({"jobs.crelate.com"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Crelate portal name: {board_token!r}")
        return f"https://jobs.crelate.com/portal/{board_token}/rss"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        items = xml_items(body)
        # The first <title> in the document is the channel's: "{Organisation} Jobs Feed".
        channel = re.search(rb"<title>([^<]*)</title>", body)
        company = channel.group(1).decode("utf-8", "replace") if channel else ""
        company = re.sub(r"\s+Jobs Feed$", "", company).strip()
        postings = []
        for item in items:
            link = (item.get("link") or [""])[0]
            title = (item.get("title") or [""])[0]
            if not link or not title:
                continue
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=link.rstrip("/").rsplit("/", 1)[-1] or stable_id(link),
                    payload={
                        "url": link,
                        "title": title,
                        "description": (item.get("description") or [""])[0] or None,
                        "location": (item.get("location") or [""])[0] or None,
                        "published": (item.get("pubdate") or [""])[0] or None,
                        "company": company or None,
                    },
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
            posted_at=feed_date(job.get("published")),
            location_text=job.get("location"),
            description_html=job.get("description"),
        )


# ---------------------------------------------------------------- GeekJob


class PathPagedJsonLdConnector(JsonLdConnector):
    """A JobPosting platform whose list is paged by path: the first page is the board
    token and page n is ``{board token}/{n}`` (GeekJob's ``/vacancies/2``)."""

    def job_pages(self, fetcher: Fetcher, board_token: str) -> list[str]:
        base = self.board_url(board_token).rstrip("/")
        links: list[str] = []
        for number in range(1, self.listing_pages + 1):
            response = fetcher.get(base if number == 1 else f"{base}/{number}")
            if response.status != 200:
                if number == 1:
                    raise FetchError("http_error", f"HTTP {response.status}", response.status)
                break
            found = page_links(response.body.decode("utf-8", "replace"), base, self.job_path)
            fresh = [link for link in found if link not in links]
            if not fresh:
                break
            links += fresh
        return links


# ---------------------------------------------------------------- Beehire

SPONTANEOUS = re.compile(r"spontan|open application|initiativ", re.IGNORECASE)
BEEHIRE_REMOTE: dict[str, RemoteStatus] = {
    "remoteWork_none": "onsite",
    "remoteWork_partial": "hybrid",
    "remoteWork_full": "remote",
}


def _translated(values: Any, language: Any) -> str | None:
    """A text kept per language index ({"0": "EN", "1": "FR"}): the posting's own language
    first, then any other that is filled in."""
    if not isinstance(values, dict):
        return None
    for key in (str(language), *values):
        text = values.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


class BeehireConnector(Connector):
    """Beehire career pages (``app.beehire.com/career/{name}``). The page is an Angular app
    that loads its jobs from ``/users/getPublicCampaigns/{name}``, which any visitor may
    call; the token is the career page name."""

    slug = "beehire"
    hosts = frozenset({"app.beehire.com"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token.lower()):
            raise ValueError(f"not a Beehire career page name: {board_token!r}")
        return f"https://app.beehire.com/users/getPublicCampaigns/{board_token}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        campaigns = data["campaigns"]
        if not isinstance(campaigns, list):
            raise ValueError("Beehire answers with a list of campaigns")
        company = (data.get("user") or {}).get("company")
        postings = []
        for campaign in campaigns:
            title = _translated(campaign.get("title"), campaign.get("language"))
            if not (campaign.get("_id") and campaign.get("inviteLink") and title):
                continue
            if SPONTANEOUS.search(title):
                continue  # the standing "apply anyway" form, not a job
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=str(campaign["_id"]),
                    payload={
                        "title": title,
                        "company": (
                            (campaign.get("customization") or {})
                            .get("employerBranding", {})
                            .get("name")
                            or company
                        ),
                        "description": _translated(
                            campaign.get("description"), campaign.get("language")
                        ),
                        "url": campaign["inviteLink"],
                        "location": campaign.get("location") or {},
                        "contract": (campaign.get("details") or {}).get("contract") or {},
                        "categories": [
                            c["label"] for c in campaign.get("jobCategories") or [] if c.get("label")
                        ],
                    },
                )
            )
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        place = job.get("location") or {}
        contract = job.get("contract") or {}
        kind = str(contract.get("type") or "")
        duration = str(contract.get("duration") or "")
        employment = (
            "Internship"
            if "internship" in kind
            else "Part-time"
            if "partTime" in duration
            else "Full-time"
            if "fullTime" in duration
            else None
        )
        city = place.get("city")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]),
            company_name=job.get("company"),
            apply_url=as_url(str(job["url"])),
            location_text=", ".join(str(p) for p in (city, place.get("country")) if p)
            or place.get("name"),
            city=city,
            workplace_type=BEEHIRE_REMOTE.get(str(contract.get("remote"))),
            employment_type=employment,
            departments=job.get("categories") or [],
            description_html=job.get("description"),
        )


WAVE2_3_CONNECTORS: list[Connector] = [
    CrelateConnector(),
    BeehireConnector(),
    PathPagedJsonLdConnector(
        "geekjob",
        r"^/vacancy/[0-9a-f]{24}$",
        frozenset({"geekjob.ru"}),
        multi_employer=True,
        listing_pages=6,
        max_pages=120,
    ),
]
