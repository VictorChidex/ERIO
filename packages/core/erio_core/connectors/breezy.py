"""Breezy HR portals: GET https://{company}.breezy.hr/json?verbose=true returns
one array of every published position, with its HTML description."""

import html
import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import iso_datetime
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,80}")


class BreezyConnector(PagedJsonConnector):
    slug = "breezy"
    hosts = frozenset({"*.breezy.hr"})

    def list_url(self, board_token: str, page: int) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Breezy company subdomain: {board_token!r}")
        return f"https://{board_token}.breezy.hr/json?verbose=true"

    def items(self, data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, list):
            raise ValueError("a Breezy portal answers with a list of positions")
        return data

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        place = job.get("location") or {}
        country = place.get("country") or {}
        state = place.get("state") or {}
        description = job.get("description")
        if job.get("salary") and description:
            description = f"<p>Salary: {html.escape(str(job['salary']))}</p>{description}"
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["name"]).strip(),
            company_name=(job.get("company") or {}).get("name"),
            apply_url=job["url"],
            posted_at=iso_datetime(job.get("published_date")),
            location_text=place.get("name") or None,
            city=place.get("city") or None,
            region=state.get("name") or None,
            country_hint=country.get("id") or country.get("name") or None,
            workplace_type="remote" if place.get("is_remote") else None,
            employment_type=(job.get("type") or {}).get("name"),
            departments=[d] if (d := job.get("department")) else [],
            description_html=description,
        )
