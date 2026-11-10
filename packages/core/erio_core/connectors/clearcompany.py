"""ClearCompany (formerly HRM Direct) career sites on apply.clearcompany.com.

Old ``{tenant}.hrmdirect.com`` addresses redirect to ``apply.clearcompany.com/{tenant}``.
That page is a shell that loads the public job widget, whose script tag names the site
(``data-site-id``); the widget then reads ``careers-api.clearcompany.com/v1/{siteId}``,
which lists every open job with its description, anonymously. The board token is the tenant
slug of the career-site address. Pages are read with ``pageIndex``/``pageSize``.
"""

import json
import re
from typing import Any

from erio_core.connectors._util import as_url, iso_datetime
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
SITE_ID = re.compile(r'data-site-id="([0-9a-fA-F-]{36})"')
PAGE = 50


class ClearCompanyConnector(Connector):
    slug = "clearcompany"
    hosts = frozenset({"apply.clearcompany.com", "careers-api.clearcompany.com"})
    max_pages = 20

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a ClearCompany career-site name: {board_token!r}")
        return f"https://apply.clearcompany.com/{board_token}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(item["id"]),
                payload=item,
            )
            for item in json.loads(body)["results"]
            if item.get("positionTitle")
        ]

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        page = fetcher.get(self.board_url(board_token))
        if page.status == 429:
            raise FetchError("rate_limited", "source rate limit", 429)
        if page.status != 200:
            raise FetchError("http_error", f"HTTP {page.status}", page.status)
        site = SITE_ID.search(page.body.decode("utf-8", "replace"))
        if not site:
            raise FetchError("parse_error", "the career site names no job widget", 200)
        postings: dict[str, RawPosting] = {}
        first = b""
        complete = True
        for index in range(self.max_pages):
            url = (
                f"https://careers-api.clearcompany.com/v1/{site[1]}"
                f"?pageIndex={index}&pageSize={PAGE}"
            )
            response = fetcher.get(url)
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                raise FetchError("http_error", f"HTTP {response.status}", response.status)
            try:
                found = self.extract(response.body, board_token)
                total = int(json.loads(response.body).get("totalCount") or 0)
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
            first = first or response.body
            fresh = [p for p in found if p.external_id not in postings]
            postings.update((p.external_id, p) for p in fresh)
            if not fresh or len(postings) >= total or len(found) < PAGE:
                break
        else:
            complete = False
        return BoardFetch(
            postings=list(postings.values()), http_status=200, body=first, complete=complete
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        job: dict[str, Any] = raw.payload
        places: list[dict[str, Any]] = job.get("locations") or []
        place = places[0] if places else {}
        remote = any(p.get("isRemote") for p in places)
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["positionTitle"]).strip(),
            company_name=job.get("brandName") or None,
            apply_url=as_url(
                job.get("applyLink") or f"https://apply.clearcompany.com/{raw.board_token}"
            ),
            posted_at=iso_datetime(job.get("postedDate") or job.get("openDate")),
            location_text=job.get("location") or None,
            city=place.get("city") or None,
            region=place.get("subdivisionFullName") or place.get("subdivision") or None,
            country_hint=place.get("country") or None,
            workplace_type="remote" if remote else None,
            departments=[job["departmentName"]] if job.get("departmentName") else [],
            description_html=job.get("description") or None,
        )
