"""SchoolSpring (education jobs) on api.schoolspring.com, the API its public site calls.

``GetPagedJobsWithSearch`` lists jobs (id, employer, title, place) for an anonymous visitor,
and ``/api/Jobs/{id}`` returns one job with its description and categories. The board
token is an employer or district name, the site's own search keyword ("Butts County
Schools"); an empty token would list the whole site, which is far too large to read here.
At most ``max_details`` jobs of a board are read per crawl, so a larger board is reported
as an incomplete fetch.
"""

import json
import re
from typing import Any
from urllib.parse import quote

from erio_core.connectors._util import as_url, iso_datetime
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.schemas import PartialJob, RawPosting

API = "https://api.schoolspring.com/api/Jobs"
TOKEN = re.compile(r"\w[\w .,&'()/-]{1,100}")
PAGE = 50


def _folded(text: object) -> str:
    return re.sub(r"\W", "", str(text)).lower()


class SchoolSpringConnector(Connector):
    slug = "schoolspring"
    hosts = frozenset({"api.schoolspring.com", "www.schoolspring.com"})
    multi_employer = True
    max_details = 60

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a SchoolSpring employer name: {board_token!r}")
        return (
            f"{API}/GetPagedJobsWithSearch?domainName=www.schoolspring.com"
            f"&keyword={quote(board_token)}&location=&category=&gradelevel=&jobtype="
            f"&organization=&swLat=&swLon=&neLat=&neLon=&page=1&size={PAGE}"
            "&sortDateAscending=false"
        )

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        jobs = json.loads(body)["value"]["jobsList"]
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["jobId"]),
                payload={"listed": job},
            )
            for job in jobs
        ]

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        response = fetcher.get(self.board_url(board_token))
        if response.status == 429:
            raise FetchError("rate_limited", "source rate limit", 429)
        if response.status != 200:
            raise FetchError("http_error", f"HTTP {response.status}", response.status)
        try:
            found = self.extract(response.body, board_token)
        except (ValueError, KeyError, TypeError) as error:
            raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
        # The keyword also matches job text: keep the employer the token names.
        wanted = _folded(board_token)
        listed = [p for p in found if wanted in _folded(p.payload["listed"].get("employer"))]
        postings: list[RawPosting] = []
        unread = 0
        for raw in listed[: self.max_details]:
            try:
                detail = fetcher.get(f"{API}/{raw.external_id}")
                info = json.loads(detail.body)["value"] if detail.status == 200 else None
            except (FetchError, ValueError, KeyError, TypeError):
                info = None
            if info is None:
                unread += 1
                continue
            postings.append(raw.model_copy(update={"payload": {**raw.payload, "detail": info}}))
        if listed and not postings:
            raise FetchError("parse_error", "no job detail could be read", 200)
        return BoardFetch(
            postings=postings,
            http_status=200,
            body=response.body,
            complete=len(found) < PAGE and len(listed) <= self.max_details and unread == 0,
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        listed: dict[str, Any] = raw.payload["listed"]
        detail: dict[str, Any] = raw.payload.get("detail") or {}
        info: dict[str, Any] = detail.get("jobInfo") or {}
        places = [p.get("displayLocation") for p in detail.get("jobLocations") or []]
        departments = list(
            dict.fromkeys(
                c["category"] for c in detail.get("jobCategories") or [] if c.get("category")
            )
        )
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(info.get("jobTitle") or listed["title"]).strip(),
            company_name=info.get("employerName") or listed.get("employer") or None,
            apply_url=as_url(f"https://www.schoolspring.com/jobs?jobid={raw.external_id}"),
            posted_at=iso_datetime(info.get("postDate") or listed.get("displayDate")),
            location_text="; ".join(dict.fromkeys(p for p in places if p))
            or listed.get("location")
            or None,
            region=info.get("stateName") or None,
            country_hint=info.get("countryName") or None,
            employment_type=info.get("jobTypeName") or None,
            departments=departments,
            description_html=info.get("jobDescription") or None,
        )
