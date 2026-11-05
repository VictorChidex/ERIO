"""SmartRecruiters posting API.

GET https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100&offset=N
returns one page of {"totalFound": n, "content": [...]}, no authentication
needed. The list has no job descriptions (those need one more request per
posting), so descriptions stay empty for this source.

An unknown company answers 200 with zero postings, the same as a company
with no openings; discovery accepts only boards that list postings anyway.

As of 2026-11-05 api.smartrecruiters.com/robots.txt disallows every crawler
but LinkedIn's, so the fetcher refuses this source until SmartRecruiters
grants access (docs/sources.md). The adapter is ready for that day.
"""

import json

from pydantic import HttpUrl

from erio_core.connectors._util import iso_datetime
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

API = "https://api.smartrecruiters.com/v1/companies"
#: The source refuses more than 100 per page; 100 pages caps one board at 10,000.
MAX_PAGES = 100


class SmartRecruitersConnector(Connector):
    slug = "smartrecruiters"
    hosts = frozenset({"api.smartrecruiters.com"})
    page_size = 100

    def board_url(self, board_token: str) -> str:
        return self._page_url(board_token, 0)

    def _page_url(self, board_token: str, offset: int) -> str:
        return f"{API}/{board_token}/postings?limit={self.page_size}&offset={offset}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        return self._read_page(body, board_token)[0]

    def _read_page(self, body: bytes, board_token: str) -> tuple[list[RawPosting], int]:
        data = json.loads(body)
        content, total = data["content"], data["totalFound"]
        if not isinstance(content, list) or not isinstance(total, int):
            raise ValueError("not a postings page")
        postings = [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["id"]),
                payload=job,
            )
            for job in content
        ]
        return postings, total

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        # Paged: no ETag, and a failure on any page fails the whole board, so a
        # half-read board never marks the unread postings as missing.
        postings: list[RawPosting] = []
        bodies: list[bytes] = []
        for page in range(MAX_PAGES):
            response = fetcher.get(self._page_url(board_token, page * self.page_size))
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", response.status)
            if response.status != 200:
                raise FetchError("http_error", f"HTTP {response.status}", response.status)
            try:
                found, total = self._read_page(response.body, board_token)
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
            postings.extend(found)
            bodies.append(response.body)
            if not found or len(postings) >= total:
                break
        else:
            raise FetchError("parse_error", f"more than {MAX_PAGES} pages", 200)
        return BoardFetch(postings=postings, http_status=200, body=b"\n".join(bodies))

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        place = job.get("location") or {}
        company = job.get("company") or {}
        workplace: RemoteStatus | None = (
            "remote" if place.get("remote") else "hybrid" if place.get("hybrid") else None
        )
        identifier = company.get("identifier") or raw.board_token
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["name"]).strip(),
            company_name=company.get("name"),
            apply_url=HttpUrl(f"https://jobs.smartrecruiters.com/{identifier}/{raw.external_id}"),
            posted_at=iso_datetime(job.get("releasedDate")),
            location_text=place.get("fullLocation") or None,
            city=place.get("city") or None,
            region=place.get("region") or None,
            country_hint=str(place["country"]).upper() if place.get("country") else None,
            workplace_type=workplace,
            employment_type=(job.get("typeOfEmployment") or {}).get("label"),
            departments=[
                label
                for label in (
                    (job.get("department") or {}).get("label"),
                    (job.get("function") or {}).get("label"),
                )
                if label
            ],
        )
