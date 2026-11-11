"""Platforms of connector wave 2/3, found by reading the reference index
(docs/reference-sources-jobindex.md). Each reads a public, unauthenticated surface that the
platform's own sites serve to every visitor; how each was found, and its limits, is in
docs/connectors.md.

- Crelate: the RSS feed behind every candidate portal (``/portal/{org}/rss``).
- GeekJob: server-rendered ``/vacancies/{n}`` lists; every vacancy page carries JobPosting data.
- Beehire: the JSON behind every career page (``/users/getPublicCampaigns/{name}``).
- Connectoor: the connectoor.jobs board search, then each job's page (JobPosting data).
- Keka: the JSON behind every Keka Hire career site (``/careers/api/jobs/default/active``).
"""

import html
import json
import re
from typing import Any

from erio_core.connectors._util import as_url, iso_datetime
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
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


# ---------------------------------------------------------------- Keka

KEKA_TOKEN = re.compile(r"([a-z0-9][a-z0-9-]{0,62})(?:/([A-Za-z0-9_-]{1,40}))?")


class KekaConnector(Connector):
    """Keka Hire career sites (``{tenant}.keka.com/careers``). Keka's own embed code and
    career page read ``/careers/api/jobs/{portal}/active``, a JSON list of every open job,
    and ``/careers/api/organization/{portal}/careerportalinfo`` for the company's name.
    robots.txt allows ``/careers``. The token is the tenant, or "tenant/portal" for a
    company with several career portals."""

    slug = "keka"
    hosts = frozenset({"*.keka.com"})

    def _parts(self, board_token: str) -> tuple[str, str]:
        match = KEKA_TOKEN.fullmatch(board_token)
        if not match:
            raise ValueError(f"not a Keka tenant (tenant or tenant/portal): {board_token!r}")
        return match[1], match[2] or "default"

    def board_url(self, board_token: str) -> str:
        tenant, portal = self._parts(board_token)
        return f"https://{tenant}.keka.com/careers/api/jobs/{portal}/active"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        jobs = json.loads(body)
        if not isinstance(jobs, list):
            raise ValueError("Keka answers with a JSON array")
        tenant, _ = self._parts(board_token)
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["id"]),
                payload={**job, "url": f"https://{tenant}.keka.com/careers/jobdetails/{job['id']}"},
            )
            for job in jobs
            if isinstance(job, dict) and job.get("id") is not None and job.get("title")
        ]

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        fetched = super().list_postings(fetcher, board_token, etag)
        if not fetched.postings:
            return fetched
        tenant, portal = self._parts(board_token)
        company = None
        try:  # the company's display name; a failure here only leaves it unnamed
            info = fetcher.get(
                f"https://{tenant}.keka.com/careers/api/organization/{portal}/careerportalinfo"
            )
            if info.status == 200:
                company = json.loads(info.body).get("name")
        except (FetchError, ValueError, AttributeError):
            company = None
        if company:
            fetched = BoardFetch(
                postings=[
                    p.model_copy(update={"payload": {**p.payload, "company": company}})
                    for p in fetched.postings
                ],
                http_status=fetched.http_status,
                body=fetched.body,
                etag=fetched.etag,
                unchanged=fetched.unchanged,
                complete=fetched.complete,
            )
        return fetched

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        places = [p for p in job.get("jobLocations") or [] if isinstance(p, dict)]
        place = places[0] if places else {}
        names = [
            ", ".join(str(x) for x in (p.get("city"), p.get("state"), p.get("countryName")) if x)
            for p in places
        ]
        department = job.get("departmentName")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("company"),
            apply_url=as_url(str(job["url"])),
            posted_at=iso_datetime(job.get("publishedOn")),
            location_text="; ".join(dict.fromkeys(n for n in names if n)) or None,
            city=place.get("city"),
            region=place.get("state"),
            country_hint=place.get("countryCode"),
            departments=[department] if department else [],
            description_html=job.get("description"),
        )


# ---------------------------------------------------------------- Connectoor

CONNECTOOR_BOARD = "https://www.connectoor.jobs"
#: The container id of the job board embedded on connectoor.jobs (printed in that page's
#: HTML for every visitor): it selects which jobs the widget search returns.
CONNECTOOR_CONTAINER = "595d038eddb233ab728b4568"
CONNECTOOR_PAGE_SIZE = 10


class ConnectoorConnector(JsonLdConnector):
    """Connectoor.jobs, the public job board of the German recruiting software Connectoor.
    Its embedded search (``api.connectoor.de/find``) lists the newest jobs ten at a time; each
    job's public page (``app.connectoor.de/jobview?jobid=``) carries a JobPosting. The board
    token is ``https://www.connectoor.jobs``."""

    def board_url(self, board_token: str) -> str:
        if board_token.rstrip("/") != CONNECTOOR_BOARD:
            raise ValueError(f"not the Connectoor board ({CONNECTOOR_BOARD}): {board_token!r}")
        return CONNECTOOR_BOARD

    def job_pages(self, fetcher: Fetcher, board_token: str) -> list[str]:
        self.board_url(board_token)
        urls: list[str] = []
        for number in range(self.listing_pages):
            response = fetcher.get(
                "https://api.connectoor.de/find"
                f"?s={CONNECTOOR_CONTAINER}&o={number * CONNECTOOR_PAGE_SIZE}&q="
            )
            if response.status != 200:
                if number == 0:
                    raise FetchError("http_error", f"HTTP {response.status}", response.status)
                break
            try:
                results = json.loads(response.body)["results"]
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed search: {error}", 200) from error
            ids = [r["id"] for r in results if isinstance(r, dict) and r.get("id")]
            if not all(re.fullmatch(r"[0-9a-f]{24}", str(i)) for i in ids):
                raise FetchError("parse_error", "unexpected job id in the search", 200)
            fresh = [f"https://app.connectoor.de/jobview?jobid={i}" for i in ids]
            fresh = [u for u in fresh if u not in urls]
            if not fresh:
                break
            urls += fresh
        return urls

    def parse(self, raw: RawPosting) -> PartialJob:
        job = super().parse(raw)
        # The pages write names with HTML entities ("Th&uuml;mmel &amp; Partner").
        return job.model_copy(
            update={
                "company_name": html.unescape(job.company_name) if job.company_name else None,
                "title": html.unescape(job.title),
            }
        )


WAVE2_3_CONNECTORS: list[Connector] = [
    CrelateConnector(),
    ConnectoorConnector(
        "connectoor",
        r"^/jobview$",
        frozenset({"www.connectoor.jobs", "api.connectoor.de", "app.connectoor.de"}),
        multi_employer=True,
        listing_pages=12,
        max_pages=120,
    ),
    BeehireConnector(),
    KekaConnector(),
    PathPagedJsonLdConnector(
        "geekjob",
        r"^/vacancy/[0-9a-f]{24}$",
        frozenset({"geekjob.ru"}),
        multi_employer=True,
        listing_pages=6,
        max_pages=120,
    ),
]
