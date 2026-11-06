"""Gem job boards: GET https://api.gem.com/job_board/v0/{board}/job_posts/
returns one array of every posting, with its HTML description. The board is
the path of its page, jobs.gem.com/{board}."""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import iso_datetime
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}")
WORKPLACE: dict[str, RemoteStatus] = {"remote": "remote", "hybrid": "hybrid", "in_office": "onsite"}


class GemConnector(PagedJsonConnector):
    slug = "gem"
    hosts = frozenset({"api.gem.com"})

    def list_url(self, board_token: str, page: int) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Gem job board name: {board_token!r}")
        return f"https://api.gem.com/job_board/v0/{board_token}/job_posts/"

    def items(self, data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, list):
            raise ValueError("a Gem job board answers with a list of postings")
        return data

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        departments = [d["name"] for d in job.get("departments") or [] if d.get("name")]
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            apply_url=job["absolute_url"],
            posted_at=iso_datetime(job.get("first_published_at") or job.get("created_at")),
            location_text=(job.get("location") or {}).get("name") or None,
            workplace_type=WORKPLACE.get(str(job.get("location_type") or "")),
            employment_type=job.get("employment_type"),
            departments=departments,
            description_html=job.get("content"),
        )
