"""Phenom People career sites: the public JSON the search page itself calls.

- list:   POST https://{host}/widgets with the page's refineSearch request
          ({"ddoKey": "refineSearch", "from": n, "size": 50, ...}); no descriptions
- detail: GET  https://{host}/{country}/{lang}/job/{jobId}, whose schema.org JobPosting
          holds the description

The board token is the career site's search address up to its locale,
"https://{host}/{country}/{lang}" (https://jobs.thermofisher.com/global/en). Sites live
on the employer's own domain, which is admitted because the board is registered.
A crawl reads at most ``max_pages`` list pages and the first ``max_details`` jobs'
pages; a larger board is reported as an incomplete fetch.
"""

import json
import re
from typing import Any
from urllib.parse import urlsplit

from erio_core.connectors._paged import PagedJsonConnector, base_url
from erio_core.connectors._util import as_url, iso_datetime
from erio_core.connectors.base import BoardFetch, Fetcher, FetchError, FetchResponse, poster
from erio_core.connectors.jsonld import job_postings
from erio_core.schemas import PartialJob, RawPosting

LOCALE = re.compile(r"/([a-z]{2,8})/([a-z]{2,3}(?:[-_][a-z]{2,4})?)/?")
PAGE = 50


def _locale(board_token: str) -> tuple[str, str]:
    base_url(board_token)
    match = LOCALE.fullmatch(urlsplit(board_token).path)
    if not match:
        raise ValueError(f"the board token must end in /{{country}}/{{lang}}: {board_token!r}")
    return match[1], match[2]


class PhenomConnector(PagedJsonConnector):
    slug = "phenom"
    hosts: frozenset[str] = frozenset()
    max_pages = 40
    max_details = 100

    def list_url(self, board_token: str, page: int) -> str:
        _locale(board_token)
        return f"{base_url(board_token)}/widgets"

    def fetch_page(self, fetcher: Fetcher, board_token: str, page: int) -> FetchResponse:
        country, lang = _locale(board_token)
        body = {
            "lang": f"{lang}_{country}", "deviceType": "desktop", "country": country,
            "pageName": "search-results", "ddoKey": "refineSearch", "sortBy": "", "subsearch": "",
            "from": (page - 1) * PAGE, "jobs": True, "counts": True,
            "all_fields": ["category", "country", "state", "city", "type"], "size": PAGE,
            "clearAll": False, "jdsource": "facets", "isSliderEnable": False, "pageId": "page20",
            "siteType": "external", "keywords": "", "global": country == "global",
            "selected_fields": {}, "locationData": {},
        }  # fmt: skip
        return poster(fetcher).post_json(self.list_url(board_token, page), body)

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["refineSearch"]["data"]["jobs"])

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return page * PAGE < int(data["refineSearch"]["totalHits"])

    def item_id(self, item: dict[str, Any]) -> str:
        return str(item["jobId"])

    def _job_page(self, board_token: str, job_id: str) -> str:
        country, lang = _locale(board_token)
        return f"{base_url(board_token)}/{country}/{lang}/job/{job_id}"

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        result = super().list_postings(fetcher, board_token, etag)
        for posting in result.postings[: self.max_details]:
            try:
                response = fetcher.get(self._job_page(board_token, posting.external_id))
            except FetchError:
                continue
            if response.status == 200:
                found = job_postings(response.body.decode("utf-8", "replace"))
                if found:
                    posting.payload["posting"] = json.loads(json.dumps(found[0], default=str))
        return result

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        posting = job.get("posting") or {}
        description = posting.get("description")
        apply_url = str(job.get("applyUrl") or "")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            apply_url=as_url(
                apply_url
                if apply_url.startswith("https://")
                else self._job_page(raw.board_token, raw.external_id)
            ),
            posted_at=iso_datetime(job.get("postedDate") or job.get("dateCreated")),
            location_text="; ".join(job.get("multi_location") or [])
            or job.get("location")
            or job.get("cityStateCountry")
            or None,
            city=job.get("city") or None,
            region=job.get("state") or None,
            country_hint=job.get("country") or None,
            employment_type=job.get("type") or None,
            departments=[d] if (d := job.get("category")) else [],
            description_html=description if isinstance(description, str) else None,
        )
