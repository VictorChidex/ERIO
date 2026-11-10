"""PyjamaHR hosted career sites (jobs.pyjamahr.com/{company}).

The career page is a Next.js app that reads ``api.pyjamahr.com/api/career/jobs/`` for
an anonymous visitor: the list gives id, slug, title and places, and
``/api/career/jobs/{id}/`` the description. The page's own data names the company and
its public uuid. (PyjamaHR's separate account API, which needs a token, is not used.)

The board token is "{company slug}/{company uuid}", both shown by the career page
(the uuid is ``companyDetails.uuid`` in the page data). At most ``max_details`` jobs are
read per crawl; a larger board is reported as an incomplete fetch.
"""

import json
import re
from typing import Any

from erio_core.connectors._util import as_url, iso_datetime
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"([a-z0-9][a-z0-9-]{0,80})/([A-Za-z0-9]{6,40})")
API = "https://api.pyjamahr.com/api/career/jobs"
WORKPLACE: dict[str, RemoteStatus] = {"REMOTE": "remote", "HYBRID": "hybrid", "ON_SITE": "onsite"}


def _parts(board_token: str) -> tuple[str, str]:
    match = TOKEN.fullmatch(board_token)
    if not match:
        raise ValueError(f"not a PyjamaHR token (slug/uuid): {board_token!r}")
    return match[1], match[2]


class PyjamaHRConnector(Connector):
    slug = "pyjamahr"
    hosts = frozenset({"api.pyjamahr.com", "jobs.pyjamahr.com"})
    max_details = 60

    def board_url(self, board_token: str) -> str:
        _, uuid = _parts(board_token)
        return f"{API}/?company_uuid={uuid}&page=1&is_careers_page=true"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        results = json.loads(body)["results"]
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["id"]),
                payload={"listed": job},
            )
            for job in results
        ]

    def _company_name(self, fetcher: Fetcher, company: str) -> str | None:
        try:
            page = fetcher.get(f"https://jobs.pyjamahr.com/{company}")
            if page.status != 200:
                return None
            data = re.search(
                r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', page.body.decode("utf-8", "replace")
            )
            name = (
                json.loads(data[1])["props"]["pageProps"]["companyDetails"]["name"] if data else ""
            )
            return str(name).strip() or None
        except (FetchError, ValueError, KeyError, TypeError):
            return None

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        company, uuid = _parts(board_token)
        listed: list[RawPosting] = []
        first = b""
        url: str | None = self.board_url(board_token)
        for _ in range(10):
            if not url:
                break
            response = fetcher.get(url)
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                raise FetchError("http_error", f"HTTP {response.status}", response.status)
            try:
                listed += self.extract(response.body, board_token)
                url = json.loads(response.body).get("next")
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
            first = first or response.body
            if url and not str(url).startswith(API):
                url = None  # a next link elsewhere is never followed
        name = self._company_name(fetcher, company)
        postings: list[RawPosting] = []
        unread = 0
        for raw in listed[: self.max_details]:
            try:
                detail = fetcher.get(
                    f"{API}/{raw.external_id}/?company_uuid={uuid}&is_careers_page=false"
                )
                info = json.loads(detail.body) if detail.status == 200 else None
            except (FetchError, ValueError):
                info = None
            if not isinstance(info, dict):
                unread += 1
                continue
            payload = {**raw.payload, "detail": info, "company": name}
            postings.append(raw.model_copy(update={"payload": payload}))
        if listed and not postings:
            raise FetchError("parse_error", "no job detail could be read", 200)
        return BoardFetch(
            postings=postings,
            http_status=200,
            body=first,
            complete=len(listed) <= self.max_details and unread == 0 and url is None,
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        listed: dict[str, Any] = raw.payload["listed"]
        detail: dict[str, Any] = raw.payload.get("detail") or {}
        company, _ = _parts(raw.board_token)
        places = [listed.get("location"), *(listed.get("other_locations") or [])]
        place = [p if isinstance(p, str) else str(p.get("name") or "") for p in places if p]
        title = str(detail.get("title") or listed["title"]).strip()
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=title,
            company_name=raw.payload.get("company") or None,
            apply_url=as_url(
                f"https://jobs.pyjamahr.com/{company}/"
                f"{listed.get('slug') or 'job'}-{raw.external_id}"
            ),
            posted_at=iso_datetime(detail.get("created_at") or detail.get("published_at")),
            location_text="; ".join(dict.fromkeys(p for p in place if p)) or None,
            country_hint=listed.get("country") or None,
            workplace_type=WORKPLACE.get(str(listed.get("workplace_type") or "").upper()),
            employment_type=detail.get("job_type") or None,
            departments=[listed["department_name"]] if listed.get("department_name") else [],
            description_html=detail.get("description") or None,
        )
