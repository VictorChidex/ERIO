"""HireHive career sites: GET https://{company}.hirehive.com/api/v1/jobs returns
{"jobs": [...], "publishedJobsCount", "nextPage"} with full descriptions."""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import epoch_seconds
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


class HireHiveConnector(PagedJsonConnector):
    slug = "hirehive"
    hosts = frozenset({"*.hirehive.com"})

    def list_url(self, board_token: str, page: int) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a HireHive company subdomain: {board_token!r}")
        base = f"https://{board_token}.hirehive.com/api/v1/jobs"
        return base if page == 1 else f"{base}?page={page}"

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["jobs"])

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return bool(data.get("nextPage"))

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        country = job.get("country") or {}
        place = ", ".join(p for p in (job.get("location"), country.get("name")) if p)
        pay = job.get("salary")
        description = (job.get("description") or {}).get("html")
        if pay and description:
            description = f"<p>Salary: {pay}</p>{description}"
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            apply_url=job["hostedUrl"],
            posted_at=epoch_seconds(job.get("publishedDate") or job.get("createdDate")),
            location_text=place or None,
            region=job.get("stateCode") or None,
            country_hint=country.get("code") or None,
            employment_type=(job.get("type") or {}).get("name"),
            departments=[c] if (c := job.get("category")) else [],
            description_html=description,
        )
