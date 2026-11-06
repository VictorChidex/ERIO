"""Hireology career sites: GET https://api.hireology.com/v2/public/careers/{slug}
returns {"data": [...], "count", "page", "page_size"} with full descriptions and
pay ranges. The slug is the path of careers.hireology.com/{slug}."""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import as_url, iso_datetime, salary
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]{0,80}")
PAGE_SIZE = 100


class HireologyConnector(PagedJsonConnector):
    slug = "hireology"
    hosts = frozenset({"api.hireology.com"})

    def list_url(self, board_token: str, page: int) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Hireology career site slug: {board_token!r}")
        return (
            f"https://api.hireology.com/v2/public/careers/{board_token}"
            f"?page_size={PAGE_SIZE}&page={page}"
        )

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["data"])

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return int(data.get("count") or 0) > page * PAGE_SIZE

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        places = job.get("locations") or [{}]
        first = places[0]
        pay = job.get("compensation") or {}
        ranged = pay.get("is_comp_range")
        low = pay.get("comp_range_min") if ranged else pay.get("comp_single_amount")
        high = pay.get("comp_range_max") if ranged else pay.get("comp_single_amount")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["name"]).strip(),
            company_name=(job.get("organization") or {}).get("name"),
            apply_url=as_url(job["career_site_url"]),
            posted_at=iso_datetime(job.get("created_at")),
            location_text=", ".join(p for p in (first.get("city"), first.get("state")) if p)
            or None,
            city=first.get("city") or None,
            region=first.get("state") or None,
            workplace_type="remote" if job.get("remote") else None,
            employment_type=job.get("employment_status"),
            departments=[d] if (d := (job.get("job_family") or {}).get("name")) else [],
            salary=salary(low, high, pay.get("comp_currency") or "USD", pay.get("comp_period")),
            description_html=job.get("job_description"),
        )
