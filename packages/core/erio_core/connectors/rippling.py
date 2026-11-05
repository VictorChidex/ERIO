"""Rippling ATS job boards: GET https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs
lists open jobs (title, location, URL); .../jobs/{uuid} adds the description,
employment type, creation date and pay ranges."""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import iso_datetime, join_html, salary
from erio_core.schemas import PartialJob, RawPosting, SalaryHint

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,80}")
BASE = "https://api.rippling.com/platform/api/ats/v1/board"


def _pay(ranges: list[dict[str, Any]]) -> SalaryHint | None:
    for pay in ranges or []:
        found = salary(
            pay.get("rangeStart"), pay.get("rangeEnd"), pay.get("currency"), pay.get("frequency")
        )
        if found:
            return found
    return None


class RipplingConnector(PagedJsonConnector):
    slug = "rippling"
    hosts = frozenset({"api.rippling.com"})

    def list_url(self, board_token: str, page: int) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Rippling board slug: {board_token!r}")
        return f"{BASE}/{board_token}/jobs"

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data)

    def item_id(self, item: dict[str, Any]) -> str:
        return str(item["uuid"])

    def detail_url(self, board_token: str, item: dict[str, Any]) -> str | None:
        return f"{BASE}/{board_token}/jobs/{item['uuid']}"

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        detail = job.get("detail") or {}
        description = detail.get("description") or {}
        places = detail.get("workLocations") or [(job.get("workLocation") or {}).get("label")]
        kind = detail.get("employmentType") or {}
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job.get("name") or detail.get("name")).strip(),
            company_name=detail.get("companyName"),
            apply_url=job["url"],
            posted_at=iso_datetime(detail.get("createdOn")),
            location_text="; ".join(p for p in places if p) or None,
            employment_type=kind.get("id") or kind.get("label"),
            departments=[d] if (d := (job.get("department") or {}).get("label")) else [],
            salary=_pay(detail.get("payRangeDetails") or []),
            description_html=join_html(description.get("company"), description.get("role")),
        )
