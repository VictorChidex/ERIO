"""Polymer job boards: GET https://api.polymer.co/v1/hire/organizations/{slug}/jobs
lists published jobs ({"items": [...], "meta": {"next_page"}}); each job's
description comes from .../jobs/{id}."""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import iso_datetime
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,80}")
BASE = "https://api.polymer.co/v1/hire/organizations"


class PolymerConnector(PagedJsonConnector):
    slug = "polymer"
    hosts = frozenset({"api.polymer.co"})

    def list_url(self, board_token: str, page: int) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Polymer organization slug: {board_token!r}")
        return f"{BASE}/{board_token}/jobs?page={page}"

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["items"])

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return bool((data.get("meta") or {}).get("next_page"))

    def detail_url(self, board_token: str, item: dict[str, Any]) -> str | None:
        return f"{BASE}/{board_token}/jobs/{item['id']}"

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload | (raw.payload.get("detail") or {})
        remoteness = str(job.get("remoteness_pretty") or "").lower()
        workplace: RemoteStatus | None = (
            "remote" if "remote" in remoteness else
            "hybrid" if "hybrid" in remoteness else
            "onsite" if remoteness else None
        )  # fmt: skip
        places = [p for p in (job.get("city"), job.get("state_region"), job.get("country")) if p]
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("organization_name"),
            apply_url=job["job_post_url"],
            posted_at=iso_datetime(job.get("published_at") or job.get("created_at")),
            location_text=job.get("display_location") or ", ".join(places) or None,
            city=job.get("city") or None,
            region=job.get("state_region") or None,
            country_hint=job.get("country") or None,
            workplace_type=workplace,
            employment_type=job.get("kind") or job.get("kind_pretty"),
            departments=[d] if (d := job.get("job_category_name")) else [],
            description_html=job.get("description"),
        )
