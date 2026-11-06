"""Dayforce candidate portals on jobs.dayforcehcm.com: the search the portal itself calls.

The portal is a NextAuth app that issues every anonymous visitor a CSRF token and cookie,
then searches jobs with them; there is no login. The token is only ever sent back to
the same host that issued it.

- session: GET https://jobs.dayforcehcm.com/api/auth/csrf  ({"csrfToken": ...}, sets a cookie)
- list:    POST /api/geo/{clientNamespace}/jobposting/search with header X-CSRF-TOKEN,
           {"clientNamespace", "jobBoardCode", "cultureCode": "en-US", "paginationStart": n}

The board token is "{clientNamespace}/{jobBoardCode}" from a career-site address
(``jobs.dayforcehcm.com/en-US/{clientNamespace}/{jobBoardCode}``). Pages hold 25 jobs, and
a crawl reads at most ``max_pages``, so a larger board is reported as an incomplete
fetch. The list carries each description as plain text, cut short on long postings. The
session cookie needs a fetcher whose client keeps cookies between requests.
"""

import html
import json
import re
from typing import Any

from erio_core.connectors._post import header_poster
from erio_core.connectors._util import as_url, iso_datetime
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"([A-Za-z0-9_-]{1,64})/([A-Za-z0-9_-]{1,64})")
HOST = "https://jobs.dayforcehcm.com"
PAGE = 25


def _parts(board_token: str) -> tuple[str, str]:
    match = TOKEN.fullmatch(board_token)
    if not match:
        raise ValueError(f"not a Dayforce token (clientNamespace/jobBoardCode): {board_token!r}")
    return match[1], match[2]


def _text_html(text: str) -> str | None:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", html.unescape(text)) if p.strip()]
    return "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs) or None


class DayforceConnector(Connector):
    slug = "dayforce"
    hosts = frozenset({"jobs.dayforcehcm.com"})
    max_pages = 40

    def board_url(self, board_token: str) -> str:
        namespace, code = _parts(board_token)
        return f"{HOST}/en-US/{namespace}/{code}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        return [self._raw(board_token, item) for item in json.loads(body)["jobPostings"]]

    def _raw(self, board_token: str, item: dict[str, Any]) -> RawPosting:
        return RawPosting(
            source_slug=self.slug,
            board_token=board_token,
            external_id=str(item["jobPostingId"]),
            payload=item,
        )

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        namespace, code = _parts(board_token)
        session = fetcher.get(f"{HOST}/api/auth/csrf")
        if session.status == 429:
            raise FetchError("rate_limited", "source rate limit", 429)
        if session.status != 200:
            raise FetchError("http_error", f"HTTP {session.status}", session.status)
        try:
            csrf = str(json.loads(session.body)["csrfToken"])
        except (ValueError, KeyError, TypeError) as error:
            raise FetchError("parse_error", "no public session token", 200) from error
        postings: dict[str, RawPosting] = {}
        first = b""
        complete = True
        for number in range(1, self.max_pages + 1):
            body = {
                "clientNamespace": namespace, "jobBoardCode": code, "cultureCode": "en-US",
                "distanceUnit": 0, "paginationStart": (number - 1) * PAGE,
            }  # fmt: skip
            response = header_poster(fetcher).post_json_with(
                f"{HOST}/api/geo/{namespace}/jobposting/search", body, {"X-CSRF-TOKEN": csrf}
            )
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                raise FetchError("http_error", f"HTTP {response.status}", response.status)
            first = first or response.body
            try:
                data = json.loads(response.body)
                items = data["jobPostings"]
                total = int(data["maxCount"])
                found = [self._raw(board_token, item) for item in items]
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
            for raw in found:
                postings[raw.external_id] = raw
            if not items or number * PAGE >= total:
                break
            if number == self.max_pages:
                complete = False
        return BoardFetch(
            postings=list(postings.values()), http_status=200, body=first, complete=complete
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        namespace, code = _parts(raw.board_token)
        places = item.get("postingLocations") or []
        first = places[0] if places else {}
        text = str(item.get("jobDescription") or "").strip()
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(item["jobTitle"]).strip(),
            apply_url=as_url(f"{HOST}/en-US/{namespace}/{code}/jobs/{raw.external_id}"),
            posted_at=iso_datetime(item.get("postingStartTimestampUTC")),
            location_text="; ".join(
                dict.fromkeys(
                    str(p["formattedAddress"]) for p in places if p.get("formattedAddress")
                )
            )
            or None,
            city=first.get("cityName") or None,
            region=first.get("stateCode") or None,
            country_hint=first.get("isoCountryCode") or None,
            workplace_type="remote" if item.get("hasVirtualLocation") else None,
            description_html=_text_html(text) if text else None,
        )
