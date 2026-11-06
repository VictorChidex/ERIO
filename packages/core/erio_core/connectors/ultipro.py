"""UltiPro (UKG Pro Recruiting) job boards on recruiting.ultipro.com.

The board token is ``{tenant}/{board GUID}`` (on recruiting.ultipro.com) or
``recruiting2.ultipro.com/{tenant}/{board GUID}``. The site's robots.txt
disallows its search API (``/JobBoardView/``), so only what the allowed board
page embeds can be read: its featured jobs, usually a handful and at most
twenty. Each featured job's detail page then holds the full job. Because the
rest of a board is out of reach, every crawl is reported incomplete and no job
is ever closed for being absent.
"""

import json
import re
from dataclasses import replace
from typing import Any

from erio_core.connectors._htmlpages import PageCrawler, listing, read_date
from erio_core.connectors._util import as_url, salary
from erio_core.connectors.base import BoardFetch, Fetcher
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

HOSTS = ("recruiting.ultipro.com", "recruiting2.ultipro.com")
TOKEN = re.compile(
    r"(?:(recruiting2?\.ultipro\.com)/)?([A-Za-z0-9]{3,30})/([0-9a-f]{8}-[0-9a-f-]{27})"
)
FEATURED = "initialFeaturedOpportunities:"
DETAIL = "CandidateOpportunityDetail("
WORKPLACES: dict[int, RemoteStatus] = {1: "onsite", 2: "hybrid", 3: "remote"}


def board_parts(board_token: str) -> tuple[str, str, str]:
    found = TOKEN.fullmatch(board_token)
    if not found:
        raise ValueError(f"not an UltiPro board token (tenant/board GUID): {board_token!r}")
    return found.group(1) or HOSTS[0], found.group(2), found.group(3)


def embedded(html: str, marker: str) -> Any:
    """The JSON value that follows ``marker`` in a page script."""
    start = html.find(marker)
    if start < 0:
        raise ValueError(f"the page has no {marker.strip('(:')}")
    value, _ = json.JSONDecoder().raw_decode(html[start + len(marker) :].lstrip())
    return value


def place(location: dict[str, Any]) -> str | None:
    address = location.get("Address") or {}
    parts = [
        address.get("City"),
        (address.get("State") or {}).get("Code") or (address.get("State") or {}).get("Name"),
        (address.get("Country") or {}).get("Name"),
    ]
    return ", ".join(p for p in parts if p) or None


class UltiProConnector(PageCrawler):
    slug = "ultipro"
    hosts = frozenset(HOSTS)

    def board_url(self, board_token: str) -> str:
        host, tenant, board = board_parts(board_token)
        return f"https://{host}/{tenant}/JobBoard/{board}/"

    def job_urls(self, fetcher: Fetcher, board_token: str) -> list[str]:
        html = listing(fetcher, self.board_url(board_token)).decode("utf-8", "replace")
        try:
            jobs = embedded(html, FEATURED)
        except json.JSONDecodeError as error:
            raise ValueError(f"malformed featured jobs: {error}") from error
        base = self.board_url(board_token)
        return [f"{base}OpportunityDetail?opportunityId={job['Id']}" for job in jobs]

    def item_id(self, url: str, page: dict[str, Any]) -> str:
        return str(page["job"]["Id"])

    def read_page(self, url: str, body: bytes) -> dict[str, Any] | None:
        job = embedded(body.decode("utf-8", "replace"), DETAIL)
        return {"job": job} if job.get("Title") else None

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        return replace(super().list_postings(fetcher, board_token, etag), complete=False)

    def parse(self, raw: RawPosting) -> PartialJob:
        job: dict[str, Any] = raw.payload["job"]
        locations = [text for loc in job.get("Locations") or [] if (text := place(loc))]
        address = ((job.get("Locations") or [{}])[0].get("Address")) or {}
        annual = (job.get("CompensationAnnualMinimum"), job.get("CompensationAnnualMaximum"))
        hourly = (job.get("CompensationHourlyMinimum"), job.get("CompensationHourlyMaximum"))
        currency = job.get("CompensationCurrencyCode") or job.get("PayRangeCurrencyCode")
        money = (
            salary(*annual, currency, "year") if any(annual) else salary(*hourly, currency, "hour")
        )
        full_time = job.get("FullTime")
        kind = None if full_time is None else ("Full-time" if full_time else "Part-time")
        category = job.get("JobCategoryName")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["Title"]).strip(),
            apply_url=as_url(str(raw.payload["url"])),
            posted_at=read_date(job.get("PostedDate")),
            location_text="; ".join(dict.fromkeys(locations)) or None,
            city=address.get("City"),
            region=(address.get("State") or {}).get("Name"),
            country_hint=(address.get("Country") or {}).get("Name"),
            workplace_type=WORKPLACES.get(job.get("JobLocationType") or 0),
            employment_type=kind,
            departments=[category] if category else [],
            salary=money,
            description_html=job.get("Description"),
        )
