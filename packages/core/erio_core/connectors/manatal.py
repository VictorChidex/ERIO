"""Manatal career pages: GET https://core.api.manatal.com/open/v3/career-page/{slug}/jobs/
returns {"count", "next", "results": [...]} with full descriptions, 100 a page.
Manatal publishes no posting date. Jobs are applied for on careers-page.com."""

import re
from typing import Any

from pydantic import HttpUrl

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,80}")
PAGE_SIZE = 100


class ManatalConnector(PagedJsonConnector):
    slug = "manatal"
    hosts = frozenset({"core.api.manatal.com"})

    def list_url(self, board_token: str, page: int) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Manatal career page slug: {board_token!r}")
        return (
            "https://core.api.manatal.com/open/v3/career-page/"
            f"{board_token}/jobs/?page={page}&page_size={PAGE_SIZE}"
        )

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["results"])

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return bool(data.get("next"))

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["position_name"]).strip(),
            apply_url=HttpUrl(f"https://www.careers-page.com/{raw.board_token}/job/{job['hash']}"),
            location_text=job.get("location_display") or job.get("address") or None,
            city=job.get("city") or None,
            region=job.get("state") or None,
            country_hint=job.get("country") or None,
            workplace_type="remote" if job.get("is_remote") else None,
            employment_type=job.get("contract_details"),
            description_html=job.get("description"),
        )
