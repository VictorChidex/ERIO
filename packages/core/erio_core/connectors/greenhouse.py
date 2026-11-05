"""Greenhouse job-board API.

GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
returns every published job on a board, no authentication needed.
"""

import html
import json
from datetime import datetime
from typing import Any

from erio_core.connectors.base import Connector
from erio_core.schemas import PartialJob, RawPosting

API = "https://boards-api.greenhouse.io/v1/boards"


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value))


class GreenhouseConnector(Connector):
    slug = "greenhouse"
    hosts = frozenset({"boards-api.greenhouse.io"})

    def board_url(self, board_token: str) -> str:
        return f"{API}/{board_token}/jobs?content=true"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        jobs = data["jobs"]
        if not isinstance(jobs, list):
            raise ValueError("'jobs' is not a list")
        # An empty board is a valid answer only when the source says so.
        if not jobs and data.get("meta", {}).get("total") != 0:
            raise ValueError("no jobs and no explicit total of zero")
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["id"]),
                payload=job,
            )
            for job in jobs
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        offices = job.get("offices") or []
        office = offices[0] if offices else {}
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("company_name"),
            apply_url=job["absolute_url"],
            posted_at=_timestamp(job.get("first_published") or job.get("updated_at")),
            location_text=(job.get("location") or {}).get("name"),
            # Offices are free text chosen by each employer; the normalizer
            # treats them as hints next to location_text.
            city=office.get("location") or None,
            country_hint=office.get("name") or None,
            departments=[d["name"] for d in job.get("departments") or [] if d.get("name")],
            description_html=html.unescape(job["content"]) if job.get("content") else None,
        )
