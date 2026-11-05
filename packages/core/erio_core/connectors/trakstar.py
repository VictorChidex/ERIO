"""Trakstar Hire (formerly Recruiterbox): the public openings API its job
widgets read. GET https://jsapi.recruiterbox.com/v1/openings?client_name={company}
returns {"meta": {"total_count", "limit", "offset"}, "objects": [...]} with full
descriptions; offset/limit pages through large boards."""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}")
LIMIT = 100


class TrakstarConnector(PagedJsonConnector):
    slug = "trakstar"
    hosts = frozenset({"jsapi.recruiterbox.com"})

    def list_url(self, board_token: str, page: int) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Trakstar Hire client name: {board_token!r}")
        offset = (page - 1) * LIMIT
        return (
            "https://jsapi.recruiterbox.com/v1/openings"
            f"?client_name={board_token}&limit={LIMIT}&offset={offset}"
        )

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["objects"])

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        meta = data.get("meta") or {}
        return int(meta.get("total_count") or 0) > page * LIMIT

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        place = job.get("location") or {}
        parts = [place.get(k) for k in ("city", "state", "country")]
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("client_name"),
            apply_url=job["hosted_url"],
            location_text=", ".join(p for p in parts if p) or None,
            city=place.get("city") or None,
            region=place.get("state") or None,
            country_hint=place.get("country") or None,
            workplace_type="remote" if job.get("allows_remote") else None,
            employment_type=job.get("position_type"),
            departments=[job["team"]] if job.get("team") else [],
            description_html=job.get("description"),
        )
