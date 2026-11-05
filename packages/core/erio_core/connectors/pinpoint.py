"""Pinpoint careers sites: GET https://{company}.pinpointhq.com/postings.json
returns every posting with its full description in one response."""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import iso_datetime, join_html, salary
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
WORKPLACE: dict[str, RemoteStatus] = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


def _department(job: dict[str, Any]) -> str | None:
    name = ((job.get("job") or {}).get("department") or {}).get("name")
    return str(name) if name else None


class PinpointConnector(PagedJsonConnector):
    slug = "pinpoint"
    hosts = frozenset({"*.pinpointhq.com"})

    def list_url(self, board_token: str, page: int) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Pinpoint subdomain: {board_token!r}")
        return f"https://{board_token}.pinpointhq.com/postings.json"

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["data"])

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        place = job.get("location") or {}
        pay_visible = job.get("compensation_visible")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            apply_url=job["url"],
            posted_at=iso_datetime(job.get("published_at") or job.get("created_at")),
            location_text=", ".join(
                p for p in (place.get("city"), place.get("province")) if p
            ) or place.get("name"),
            city=place.get("city"),
            region=place.get("province"),
            workplace_type=WORKPLACE.get(str(job.get("workplace_type") or "")),
            employment_type=job.get("employment_type"),
            departments=[d] if (d := _department(job)) else [],
            salary=salary(
                job.get("compensation_minimum"),
                job.get("compensation_maximum"),
                job.get("compensation_currency"),
                job.get("compensation_frequency"),
            ) if pay_visible else None,
            description_html=join_html(
                job.get("description"),
                job.get("key_responsibilities"),
                job.get("skills_knowledge_expertise"),
                job.get("benefits"),
            ),
        )  # fmt: skip
