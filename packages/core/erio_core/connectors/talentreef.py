"""talentReef career sites on apply.jobappnetwork.com: the search the page itself calls.

The career site is a React page that searches jobs by POSTing an Elasticsearch query to
the production search address its own script ships to every visitor. There is no login
and no token: the request carries only a JSON body.

- list: POST https://prod-kong.internal.talentreef.com/apply/proxy-es/search-en-us/posting/_search
        {"from": n, "size": 100, "query": {"bool": {"filter": [clientId, externalOnly]}}}

The board token is the numeric client id from a career-site address
(``apply.jobappnetwork.com/clients/{id}/...``). Descriptions come inline. The page's
own query asks for postings open to external applicants, and so does this one. A crawl
reads at most ``max_pages`` pages of 100, and a larger board is reported as an
incomplete fetch. The host name says "internal" but it is the address the public page
uses, and it answers any anonymous visitor.
"""

import json
import re
from datetime import UTC, datetime
from typing import Any

from erio_core.connectors._util import as_url, salary
from erio_core.connectors.base import (
    BoardFetch,
    Connector,
    Fetcher,
    FetchError,
    poster,
)
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"\d{1,8}")
SEARCH = "https://prod-kong.internal.talentreef.com/apply/proxy-es/search-en-us/posting/_search"
PAGE = 100
FIELDS = [
    "positionType", "category", "description", "address", "jobId", "clientId", "clientName",
    "brand", "internalOrExternal", "contractType", "createdDate", "isSalaried",
    "minCompensation", "maxCompensation", "pubCompensation",
]  # fmt: skip
CURRENCIES = {"US": "USD", "CA": "CAD", "GB": "GBP"}


def _client(board_token: str) -> int:
    if not TOKEN.fullmatch(board_token):
        raise ValueError(f"not a talentReef token (numeric client id): {board_token!r}")
    return int(board_token)


def _query(client: int, start: int) -> dict[str, Any]:
    return {
        "from": start,
        "size": PAGE,
        "_source": FIELDS,
        "query": {
            "bool": {
                "filter": [
                    {"terms": {"clientId.raw": [str(client)]}},
                    {"terms": {"internalOrExternal": ["externalOnly"]}},
                ]
            }
        },
        "sort": [{"jobId.raw": {"order": "asc"}}],
    }


class TalentReefConnector(Connector):
    slug = "talentreef"
    hosts = frozenset({"prod-kong.internal.talentreef.com"})
    max_pages = 20

    def board_url(self, board_token: str) -> str:
        _client(board_token)
        return SEARCH

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        hits = json.loads(body)["hits"]["hits"]
        return [self._raw(board_token, hit["_source"]) for hit in hits]

    def _raw(self, board_token: str, source: dict[str, Any]) -> RawPosting:
        return RawPosting(
            source_slug=self.slug,
            board_token=board_token,
            external_id=str(source["jobId"]),
            payload=source,
        )

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        client = _client(board_token)
        postings: dict[str, RawPosting] = {}
        first = b""
        complete = True
        for number in range(1, self.max_pages + 1):
            response = poster(fetcher).post_json(SEARCH, _query(client, (number - 1) * PAGE))
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                raise FetchError("http_error", f"HTTP {response.status}", response.status)
            first = first or response.body
            try:
                hits = json.loads(response.body)["hits"]
                items = hits["hits"]
                total = int(hits["total"])
                found = [self._raw(board_token, item["_source"]) for item in items]
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
        address = item.get("address") or {}
        city = str(address.get("city") or "").strip()
        region = str(address.get("stateOrProvince") or "").strip()
        country = str(address.get("country") or "").strip()
        place = ", ".join(p for p in (city, region, country) if p)
        try:
            posted = datetime.strptime(str(item.get("createdDate")), "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            posted = None
        pay = (
            salary(
                item.get("minCompensation"),
                item.get("maxCompensation"),
                CURRENCIES.get(country.upper()),
                "year" if item.get("isSalaried") else "hour",
            )
            if item.get("pubCompensation")
            else None
        )
        category = str(item.get("category") or "").strip()
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(item["positionType"]).strip(),
            company_name=str(item.get("clientName") or "").strip() or None,
            apply_url=as_url(
                f"https://apply.jobappnetwork.com/clients/{int(raw.board_token)}"
                f"/posting/{raw.external_id}/en"
            ),
            posted_at=posted,
            location_text=place or None,
            city=city.title() or None,
            region=region or None,
            country_hint=country or None,
            employment_type=str(item.get("contractType") or "") or None,
            departments=[category] if category else [],
            salary=pay,
            description_html=str(item.get("description") or "").strip() or None,
        )
