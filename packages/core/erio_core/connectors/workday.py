"""Workday career sites (myworkdayjobs.com): the public JSON the career page itself calls.

- list:   POST https://{tenant}.{wdN}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
          with {"limit": 20, "offset": n}; at most 20 a page, and the total stops at 2,000
- detail: GET  https://{tenant}.{wdN}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}

The board token is "{tenant}.{wdN}/{site}" taken from a career-site address such
as https://salesforce.wd12.myworkdayjobs.com/External_Career_Site. The list has no
descriptions: a crawl reads the first ``max_details`` jobs' detail pages and at most
``max_pages`` list pages, and a larger board is reported as an incomplete fetch, so
jobs not read this time are never closed for being absent.
"""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import as_url, iso_datetime
from erio_core.connectors.base import Fetcher, FetchResponse, poster
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

# A job at several places lists only how many ("3 Locations"); its address path names the first.
LOCATION_COUNT = re.compile(r"^\d+ locations?$", re.IGNORECASE)
COUNTRY_CODE = re.compile(r"[A-Z]{2,3}")


def path_place(path: str) -> str | None:
    """The place in a job's address: ``/job/US-CA-Santa-Clara/Title_JR1`` is Santa Clara, CA, US."""
    parts = path.split("/")
    if len(parts) < 4 or parts[1] != "job" or not parts[2]:
        return None
    slug = parts[2]
    if "---" in slug:  # "USA---Florida---Tampa", written broad to narrow
        return slug.replace("---", "-")
    pieces = [piece for piece in slug.split("-") if piece]
    if len(pieces) >= 3 and COUNTRY_CODE.fullmatch(pieces[0]) and len(pieces[1]) == 2:
        return f"{' '.join(pieces[2:])}, {pieces[1]}, {pieces[0]}"
    if len(pieces) >= 2 and COUNTRY_CODE.fullmatch(pieces[0]):
        return f"{' '.join(pieces[1:])}, {pieces[0]}"
    return " ".join(pieces) or None


TOKEN = re.compile(r"([a-z0-9][a-z0-9-]{0,62})\.(wd\d{1,3})/([A-Za-z0-9][A-Za-z0-9_-]{0,80})")
PAGE = 20


def _parts(board_token: str) -> tuple[str, str, str]:
    match = TOKEN.fullmatch(board_token)
    if not match:
        raise ValueError(f"not a Workday token (tenant.wdN/site): {board_token!r}")
    return match[1], match[2], match[3]


def _workplace(text: str | None) -> RemoteStatus | None:
    folded = (text or "").lower()
    if "remote" in folded:
        return "remote"
    return "hybrid" if "hybrid" in folded else None


class WorkdayConnector(PagedJsonConnector):
    slug = "workday"
    # Tenants live under a data centre: tenant.wd5.myworkdayjobs.com, tenant.wd103.…
    hosts = frozenset(f"*.wd{n}.myworkdayjobs.com" for n in [*range(1, 13), *range(100, 111)])
    max_pages = 50
    max_details = 200

    def _api(self, board_token: str) -> str:
        tenant, datacenter, site = _parts(board_token)
        return f"https://{tenant}.{datacenter}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"

    def list_url(self, board_token: str, page: int) -> str:
        return f"{self._api(board_token)}/jobs"

    def fetch_page(self, fetcher: Fetcher, board_token: str, page: int) -> FetchResponse:
        body = {"limit": PAGE, "offset": (page - 1) * PAGE, "appliedFacets": {}, "searchText": ""}
        return poster(fetcher).post_json(self.list_url(board_token, page), body)

    def items(self, data: Any) -> list[dict[str, Any]]:
        # Workday lists hidden postings as bare stubs ({"bulletFields": [...]}): skip them.
        return [j for j in data["jobPostings"] if j.get("title") and j.get("externalPath")]

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        # Workday sends "total" on the first page only: a full page means more may follow.
        return len(data["jobPostings"]) >= PAGE

    def item_id(self, item: dict[str, Any]) -> str:
        fields = item.get("bulletFields") or []
        return str(fields[0] if fields else item["externalPath"].rsplit("/", 1)[-1])

    def detail_url(self, board_token: str, item: dict[str, Any]) -> str | None:
        return f"{self._api(board_token)}{item['externalPath']}"

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        info = (item.get("detail") or {}).get("jobPostingInfo") or {}
        tenant, datacenter, site = _parts(raw.board_token)
        summary = item.get("locationsText")
        if isinstance(summary, str) and LOCATION_COUNT.match(summary.strip()):
            summary = path_place(str(item.get("externalPath"))) or summary  # "3 Locations"
        places = [info.get("location") or summary]
        places += info.get("additionalLocations") or []
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(info.get("title") or item["title"]).strip(),
            company_name=((item.get("detail") or {}).get("hiringOrganization") or {}).get("name"),
            apply_url=as_url(
                info.get("externalUrl")
                or f"https://{tenant}.{datacenter}.myworkdayjobs.com/{site}{item['externalPath']}"
            ),
            posted_at=iso_datetime(info.get("startDate")),
            location_text="; ".join(p for p in places if p) or None,
            country_hint=(info.get("country") or {}).get("descriptor"),
            workplace_type=_workplace(info.get("remoteType")),
            employment_type=info.get("timeType"),
            description_html=info.get("jobDescription"),
        )
