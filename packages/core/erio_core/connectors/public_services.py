"""Government job services: public employment services that publish their vacancies.

Each lists the jobs of many employers (``multi_employer``) with the employer in
the posting, needs no access key or sign-in, and is read through the polite
fetcher (robots.txt, rate limit). What each asks in return is repeated in its
entry of ``erio_core/data/platforms.json`` and on the coverage page.

- Arbetsformedlingen (https://jobsearch.api.jobtechdev.se): the Swedish Public
  Employment Service's JobSearch API; the ads are licensed CC0, credit
  "Arbetsformedlingen / JobTech" is given anyway. The API pages at most 2,100
  ads, so a crawl reads the newest of them and reports the rest as partial.
- EURES (https://europa.eu/eures): the European Job Mobility Portal's public
  vacancy search, fed by the national employment services. Re-use is authorised
  when the European Labour Authority (EURES) is acknowledged as the source; the
  EURES logo is not used. The portal's robots.txt asks for a 10 second delay
  between requests, which the fetcher keeps, so a crawl reads a few pages.
- Werken voor Nederland (https://www.werkenvoornederland.nl): the Dutch central
  government's vacancies, read from each vacancy page's schema.org JobPosting
  and article text. Its content is under CC0, with no credit required.
"""

import json
import re
from typing import Any

from erio_core.connectors._htmlpages import element_at
from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._service import plain, service_host
from erio_core.connectors._util import as_url, epoch_ms, iso_datetime, join_html
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError, poster
from erio_core.connectors.jsonld import JsonLdConnector, parse_job_posting
from erio_core.schemas import PartialJob, RawPosting

# Arbetsformedlingen -------------------------------------------------------------------

JOBTECH_PAGE = 100
JOBTECH_MAX_OFFSET = 2000  # the API refuses a larger offset
PART_TIME_BELOW = 100  # percent of full time

SWEDISH_EMPLOYMENT = {
    "heltid": "Full-time",
    "deltid": "Part-time",
    "sommarjobb / feriejobb": "Temporary",
    "behovsanställning": "Temporary",
    "vikariat": "Temporary",
}


class ArbetsformedlingenConnector(PagedJsonConnector):
    slug = "arbetsformedlingen"
    hosts = frozenset({"jobsearch.api.jobtechdev.se"})
    multi_employer = True
    max_pages = JOBTECH_MAX_OFFSET // JOBTECH_PAGE + 1

    def list_url(self, board_token: str, page: int) -> str:
        host = service_host(board_token, self.hosts, "Arbetsformedlingen")
        offset = (page - 1) * JOBTECH_PAGE
        return f"https://{host}/search?limit={JOBTECH_PAGE}&offset={offset}&sort=pubdate-desc"

    def items(self, data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict) or not isinstance(data.get("hits"), list):
            raise ValueError("JobSearch answers with {total, hits: [...]}")
        return [hit for hit in data["hits"] if not hit.get("removed")]

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        total = int((data.get("total") or {}).get("value") or 0)
        return page * JOBTECH_PAGE < total

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        address = job.get("workplace_address") or {}
        employer = job.get("employer") or {}
        details = job.get("application_details") or {}
        link = str(details.get("url") or "")
        apply_url = link if link.lower().startswith(("https://", "http://")) else job["webpage_url"]
        hours = str((job.get("working_hours_type") or {}).get("label") or "").lower()
        kind = str((job.get("employment_type") or {}).get("label") or "").lower()
        scope = job.get("scope_of_work") or {}
        part_time = (scope.get("max") or PART_TIME_BELOW) < PART_TIME_BELOW
        employment = SWEDISH_EMPLOYMENT.get(hours) or SWEDISH_EMPLOYMENT.get(kind)
        if employment is None and part_time:
            employment = "Part-time"
        model = str((job.get("workplace_model") or {}).get("label") or "").lower()
        place = [address.get("municipality"), address.get("region")]
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=plain(job["headline"]) or "",
            company_name=plain(employer.get("name") or employer.get("workplace")),
            apply_url=as_url(apply_url),
            posted_at=iso_datetime(job.get("publication_date")),
            location_text=", ".join(str(p) for p in place if p) or None,
            city=plain(address.get("municipality")),
            region=plain(address.get("region")),
            country_hint="SE",
            workplace_type="remote" if model.startswith("dist") else None,
            employment_type=employment,
            departments=[
                str(f["label"]) for f in [job.get("occupation_field")] if f and f.get("label")
            ],
            description_html=_paragraphs((job.get("description") or {}).get("text")),
        )


def _paragraphs(text: Any) -> str | None:
    """Plain text with blank-line paragraphs as HTML, so line breaks survive."""
    if not text or not str(text).strip():
        return None
    blocks = [b.strip() for b in re.split(r"\n\s*\n", str(text)) if b.strip()]
    escaped = [b.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") for b in blocks]
    return "".join(f"<p>{b.replace(chr(10), '<br>')}</p>" for b in escaped)


# EURES --------------------------------------------------------------------------------

EURES_PAGE = 50
EURES_SCHEDULES = {"fulltime": "Full-time", "parttime": "Part-time"}
EURES_SEARCH = {
    "page": 1,
    "resultsPerPage": EURES_PAGE,
    "sortSearch": "MOST_RECENT",
    "keywords": [],
    "publicationPeriod": None,
    "occupationUris": [],
    "skillUris": [],
    "requiredExperienceCodes": [],
    "positionScheduleCodes": [],
    "sectorCodes": [],
    "educationAndQualificationLevelCodes": [],
    "positionOfferingCodes": [],
    "locationCodes": [],
    "euresFlagCodes": [],
    "otherBenefitsCodes": [],
    "requiredLanguages": [],
    "minNumberPost": None,
}


class EuresConnector(Connector):
    slug = "eures"
    hosts = frozenset({"europa.eu"})
    multi_employer = True
    # robots.txt asks for 10 seconds between requests: five pages of 50 is a minute.
    max_pages = 5

    def board_url(self, board_token: str) -> str:
        host = service_host(board_token, self.hosts, "EURES")
        return f"https://{host}/eures/api/jv-searchengine/public/jv-search/search"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        return [self._raw(board_token, job) for job in self._jobs(json.loads(body))]

    @staticmethod
    def _jobs(data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict) or not isinstance(data.get("jvs"), list):
            raise ValueError("EURES answers with {numberRecords, jvs: [...]}")
        return list(data["jvs"])

    def _raw(self, board_token: str, job: dict[str, Any]) -> RawPosting:
        return RawPosting(
            source_slug=self.slug,
            board_token=board_token,
            external_id=str(job["id"]),
            payload=job,
        )

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        url = self.board_url(board_token)
        post = poster(fetcher)
        jobs: dict[str, dict[str, Any]] = {}
        first = b""
        complete = True
        for page in range(1, self.max_pages + 1):
            response = post.post_json(url, EURES_SEARCH | {"page": page})
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                raise FetchError("http_error", f"HTTP {response.status}", response.status)
            try:
                data = json.loads(response.body)
                found = self._jobs(data)
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
            first = first or response.body
            for job in found:
                jobs.setdefault(str(job["id"]), job)
            if len(found) < EURES_PAGE:
                break
            if page == self.max_pages:
                complete = False
        postings = [self._raw(board_token, job) for job in jobs.values()]
        return BoardFetch(postings=postings, http_status=200, body=first, complete=complete)

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        places = job.get("locationMap") or {}
        country = next(iter(places), None)
        schedules = [EURES_SCHEDULES[c] for c in job.get("positionScheduleCodes") or []
                     if c in EURES_SCHEDULES]  # fmt: skip
        employer = job.get("employer") or {}
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=plain(job["title"]) or "",
            company_name=plain(employer.get("name")),
            apply_url=as_url(
                f"https://europa.eu/eures/portal/jv-se/jv-details/{job['id']}?lang=en"
            ),
            posted_at=epoch_ms(job.get("creationDate")),
            country_hint=country if country and len(country) == 2 else None,
            employment_type=", ".join(schedules) or None,
            description_html=_paragraphs_if_text(job.get("description")),
        )


def _paragraphs_if_text(text: Any) -> str | None:
    """The portal sends HTML for most vacancies and plain text for some."""
    if not text or not str(text).strip():
        return None
    return str(text).strip() if "<" in str(text) else _paragraphs(text)


# Werken voor Nederland ----------------------------------------------------------------

WVN_SITEMAP = "https://www.werkenvoornederland.nl/sitemap-vacatures.xml"
ARTICLE = re.compile(r'<div[^>]*class="[^"]*\bs-article-content\b[^"]*"[^>]*>')


class WerkenVoorNederlandConnector(JsonLdConnector):
    """Vacancy pages carry a JobPosting with a one-line summary; the vacancy text is in
    the page's article blocks, so it is added to the payload and used as the description."""

    multi_employer = True

    def __init__(self) -> None:
        super().__init__(
            "werkenvoornederland",
            r"^/vacatures/[^/]+$",
            frozenset({"www.werkenvoornederland.nl"}),
            max_pages=200,
            multi_employer=True,
        )

    def board_url(self, board_token: str) -> str:
        if board_token != WVN_SITEMAP:
            raise ValueError(f"not a Werken voor Nederland token ({WVN_SITEMAP}): {board_token!r}")
        return board_token

    def _postings(self, html: str, page_url: str) -> list[RawPosting]:
        postings = super()._postings(html, page_url)
        blocks = [element_at(html, m.start()) for m in ARTICLE.finditer(html)]
        article = join_html(*(f"<div>{b}</div>" for b in blocks if b and b.strip()))
        return [
            p.model_copy(update={"payload": p.payload | {"article_html": article}})
            for p in postings
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        payload = raw.payload
        job = parse_job_posting(
            self.slug, raw.external_id, str(payload["page_url"]), payload["posting"]
        )
        article = payload.get("article_html")
        return job.model_copy(update={"description_html": article or job.description_html})


PUBLIC_SERVICE_CONNECTORS: list[Connector] = [
    ArbetsformedlingenConnector(),
    EuresConnector(),
    WerkenVoorNederlandConnector(),
]
