"""Oracle Taleo Enterprise career sections: the public JSON the job search page calls.

- list:   POST https://{tenant}.taleo.net/careersection/rest/jobboard/searchjobs?lang=en&portal={portal}
          with {"pageNo": n, ...} and a ``tz`` request header; 25 jobs a page
- detail: GET  https://{tenant}.taleo.net/careersection/{section}/jobdetail.ftl?job={contestNo}

The board token is "{tenant}/{section}/{portalNo}": the section is in the career-site
address (/careersection/ex/jobsearch.ftl) and ``portalNo`` is printed in that page's
script. List columns are configured per section, so the title is the linked column,
the location the location column and the date the first column that reads as one.
The detail page carries the description, which a crawl reads for the first
``max_details`` jobs only; a larger board is reported as an incomplete fetch.
"""

import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._post import header_poster
from erio_core.connectors._util import as_url
from erio_core.connectors.base import BoardFetch, Fetcher, FetchError, FetchResponse
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"([a-z0-9][a-z0-9-]{0,62})/([A-Za-z0-9_]{1,40})/(\d{3,20})")
PAGE = 25
DATE = re.compile(r"[A-Z][a-z]{2} \d{1,2}, \d{4}")
FILL = re.compile(r"fillList\('requisitionDescriptionInterface', 'descRequisition', \[(.*?)\]\);")
QUOTED = re.compile(r"'((?:[^'\\]|\\.)*)'")
EMPLOYMENT = re.compile(r"(full|part)[- ]time|contract|temporary|intern(ship)?|casual", re.I)


def _parts(board_token: str) -> tuple[str, str, str]:
    match = TOKEN.fullmatch(board_token)
    if not match:
        raise ValueError(f"not a Taleo token (tenant/section/portalNo): {board_token!r}")
    return match[1], match[2], match[3]


def _posted(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%b %d, %Y").replace(tzinfo=UTC)
    except ValueError:
        return None


def _detail(html: str) -> dict[str, Any]:
    """What the job page's script holds: the description blocks and the plain fields."""
    found = FILL.search(html)
    if not found:
        return {}
    values = [unquote(v) for v in QUOTED.findall(found[1])][2:]
    blocks = list(dict.fromkeys(v[3:] for v in values if v.startswith("!*!")))
    kinds = [v for v in values if len(v) < 40 and EMPLOYMENT.fullmatch(v.strip())]
    return {"description": "".join(blocks), "employment": kinds[0] if kinds else None}


class TaleoConnector(PagedJsonConnector):
    slug = "taleo"
    hosts = frozenset({"*.taleo.net"})
    max_pages = 40
    max_details = 100

    def list_url(self, board_token: str, page: int) -> str:
        tenant, _, portal = _parts(board_token)
        return (
            f"https://{tenant}.taleo.net/careersection/rest/jobboard/searchjobs"
            f"?lang=en&portal={portal}"
        )

    def fetch_page(self, fetcher: Fetcher, board_token: str, page: int) -> FetchResponse:
        body = {
            "multilineEnabled": False,
            "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
            "fieldData": {"fields": {"KEYWORD": "", "LOCATION": "", "CATEGORY": ""}, "valid": True},
            "filterSelectionParam": {"searchFilterSelections": []},
            "advancedSearchFiltersSelectionParam": {"searchFilterSelections": []},
            "pageNo": page,
        }
        return header_poster(fetcher).post_json_with(
            self.list_url(board_token, page), body, {"tz": "GMT+00:00"}
        )

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["requisitionList"])

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return page * PAGE < int(data["pagingData"]["totalCount"])

    def item_id(self, item: dict[str, Any]) -> str:
        return str(item["contestNo"])

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        result = super().list_postings(fetcher, board_token, etag)
        tenant, section, _ = _parts(board_token)
        for posting in result.postings[: self.max_details]:
            url = f"https://{tenant}.taleo.net/careersection/{section}/jobdetail.ftl"
            try:
                response = fetcher.get(f"{url}?job={posting.external_id}&lang=en")
            except FetchError:
                continue
            if response.status == 200:
                posting.payload["detail"] = _detail(response.body.decode("utf-8", "replace"))
        return result

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        tenant, section, _ = _parts(raw.board_token)
        columns = [str(c) for c in item.get("column") or []]
        title = columns[item.get("linkedColumn") or 0]
        places: list[str] = []
        for index in item.get("locationsColumns") or []:
            text = columns[index] if index < len(columns) else ""
            parsed = json.loads(text) if text.startswith("[") else [text]
            places += [p for p in parsed if p]
        detail = item.get("detail") or {}
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=title.strip(),
            apply_url=as_url(
                f"https://{tenant}.taleo.net/careersection/{section}/jobdetail.ftl"
                f"?job={raw.external_id}&lang=en"
            ),
            posted_at=next((d for c in columns if DATE.fullmatch(c) and (d := _posted(c))), None),
            location_text="; ".join(dict.fromkeys(places)) or None,
            employment_type=detail.get("employment"),
            description_html=detail.get("description") or None,
        )
