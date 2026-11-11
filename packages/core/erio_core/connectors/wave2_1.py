"""Second reference wave, batch 1: platforms found by reading the reference site jobindex.space.

Each reads a public, unauthenticated surface that the platform's own career sites serve to
every visitor; how each was found, and its limits, is in docs/connectors.md.

- greytHR Hire: the career page's own JSON calls on ``{tenant}.greythr.com/hire``.
- d.vinci: the career site sitemap plus the JobPosting each job page carries.
- Friend.work: the JSON the portal page reads from api.friend.work (one call, all vacancies).
"""

import json
import re
from typing import Any

from erio_core.connectors._service import plain
from erio_core.connectors._util import as_url, iso_datetime
from erio_core.connectors.jsonld import JsonLdConnector
from erio_core.connectors.jsonld_platforms import hosts
from erio_core.connectors.base import (
    BoardFetch,
    Connector,
    Fetcher,
    FetchError,
    poster,
)
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus, SalaryHint

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


def _status(status: int) -> None:
    if status == 429:
        raise FetchError("rate_limited", "source rate limit", 429)
    if status != 200:
        raise FetchError("http_error", f"HTTP {status}", status)


def _json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except ValueError as error:
        raise FetchError("parse_error", f"not JSON: {error}", 200) from error


# ------------------------------------------------------------- greytHR Hire


class GreytHRHireConnector(Connector):
    """greytHR Hire career sites: ``https://{tenant}.greythr.com/hire/jobs/``.

    The page is a script that POSTs ``/hire/api/career/published_jobs/`` (every published
    job, description included), and reads the company name and the place names from two
    GET calls. Locations come as ids, resolved with the ``emp-category`` lookup.
    """

    slug = "greythr"
    hosts = frozenset({"*.greythr.com"})

    def _base(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a greytHR subdomain: {board_token!r}")
        return f"https://{board_token}.greythr.com/hire"

    def board_url(self, board_token: str) -> str:
        return f"{self._base(board_token)}/api/career/published_jobs/"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        jobs = data["data"] if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            raise ValueError("greytHR answers with {data: [...]}")
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["id"]),
                payload={k: v for k, v in job.items() if not k.startswith("added_by")},
            )
            for job in jobs
            if isinstance(job, dict) and job.get("id") and job.get("title")
        ]

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        base = self._base(board_token)
        listed = poster(fetcher).post_json(self.board_url(board_token), {})
        _status(listed.status)
        try:
            postings = self.extract(listed.body, board_token)
        except (ValueError, KeyError, TypeError) as error:
            raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
        company: str | None = None
        places: dict[str, str] = {}
        if postings:
            details = fetcher.get(f"{base}/api/career/get_company_details/")
            if details.status == 200:
                company = plain(_json(details.body).get("company_name"))
            lookup = fetcher.get(f"{base}/api/greythr/emp-category/")
            if lookup.status == 200:
                places = self._places(_json(lookup.body))
        enriched = [
            raw.model_copy(update={"payload": {**raw.payload, "_company": company, "_places": places}})
            for raw in postings
        ]
        return BoardFetch(postings=enriched, http_status=200, body=listed.body)

    @staticmethod
    def _places(lookup: dict[str, Any]) -> dict[str, str]:
        category = str((lookup.get("cat_extfield") or {}).get("location") or "")
        return {
            str(ident): str(value["name"])
            for ident, value in (lookup.get("value") or {}).items()
            if str(value.get("cat_id")) == category and value.get("name")
        }

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        places: dict[str, str] = job.get("_places") or {}
        names = [places[str(i)] for i in job.get("locations") or [] if str(i) in places]
        remote = bool(job.get("is_remote"))
        workplace: RemoteStatus | None = "remote" if remote else None
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("_company"),
            apply_url=as_url(str(job["apply_url"])),
            posted_at=iso_datetime(job.get("published_on_career_page") or job.get("created_at")),
            location_text="; ".join(dict.fromkeys(names)) or ("Remote" if remote else None),
            workplace_type=workplace,
            employment_type=plain(job.get("job_type")),
            description_html=job.get("description") or None,
        )


# ---------------------------------------------------------------- Friend.work

FRIENDWORK_CURRENCIES = {0: "RUB", 1: "USD", 2: "EUR", 3: "UAH", 4: "KZT", 5: "BYN", 6: "AED", 7: "UZS"}
FRIENDWORK_PLACES: dict[str, RemoteStatus] = {
    "office": "onsite", "remote": "remote", "hybrid": "hybrid"
}  # fmt: skip
FRIENDWORK_PORTAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


class FriendWorkConnector(Connector):
    """Friend.work career portals: ``https://jobs.friend.work/{portal}``.

    The portal page is a script that reads ``api.friend.work/Publication/CareerPortal``
    for the portal's name; one call returns the company and every published vacancy with
    its description. The board token is the portal name (the first path segment).
    """

    slug = "friendwork"
    hosts = frozenset({"api.friend.work"})

    def board_url(self, board_token: str) -> str:
        if not FRIENDWORK_PORTAL.fullmatch(board_token):
            raise ValueError(f"not a Friend.work portal name: {board_token!r}")
        return f"https://api.friend.work/Publication/CareerPortal?token={board_token}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        jobs = data["publications"]
        if not isinstance(jobs, list):
            raise ValueError("Friend.work answers with a publications list")
        company = plain((data.get("company") or {}).get("name"))
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["publishedJobId"]),
                payload={
                    **{k: v for k, v in job.items() if k not in ("applicationBaseFields",)},
                    "_company": company,
                },
            )
            for job in jobs
            if isinstance(job, dict) and job.get("publishedJobId") and job.get("title")
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        city = plain(job.get("city"))
        address = plain(job.get("address"))
        low, high = job.get("salaryFrom") or None, job.get("salaryTo") or None
        currency = FRIENDWORK_CURRENCIES.get(job.get("currency") or 0)
        pay = (
            SalaryHint(min=low, max=high, currency=currency, period="month")
            if (low or high) and currency
            else None
        )
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("_company"),
            apply_url=as_url(f"https://jobs.friend.work/{raw.board_token}/{raw.external_id}"),
            posted_at=iso_datetime(job.get("publishDateTime") or job.get("dateCreated")),
            location_text=", ".join(p for p in (city, address) if p) or None,
            city=city,
            workplace_type=FRIENDWORK_PLACES.get(str(job.get("workplaceType") or "").lower()),
            employment_type=plain(job.get("employmentType")),
            salary=pay,
            description_html=job.get("description") or None,
        )


WAVE2_1_CONNECTORS: list[Connector] = [
    GreytHRHireConnector(),
    FriendWorkConnector(),
    # d.vinci career sites: a sitemap of /{lang}/jobs/{id}/{slug} pages, each with a JobPosting.
    JsonLdConnector("dvinci", r"^/[a-z]{2}/jobs/\d+/", hosts("*.dvinci-hr.com", "*.dvinci.de")),
]
