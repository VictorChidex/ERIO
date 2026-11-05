"""Lever postings API.

GET https://api.lever.co/v0/postings/{company}?mode=json returns every
published posting as a JSON list, no authentication needed. An unknown
company answers 404; a company with no openings answers an empty list.
"""

import json

from erio_core.connectors._util import epoch_ms, join_html, salary
from erio_core.connectors.base import Connector
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

API = "https://api.lever.co/v0/postings"
WORKPLACE: dict[str, RemoteStatus] = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


class LeverConnector(Connector):
    slug = "lever"
    hosts = frozenset({"api.lever.co"})

    def board_url(self, board_token: str) -> str:
        return f"{API}/{board_token}?mode=json"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        jobs = json.loads(body)
        if not isinstance(jobs, list):
            raise ValueError("response is not a list of postings")
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
        categories = job.get("categories") or {}
        places = categories.get("allLocations") or [categories.get("location")]
        pay = job.get("salaryRange") or {}
        sections = "".join(
            f"<h3>{section.get('text', '')}</h3><ul>{section.get('content', '')}</ul>"
            for section in job.get("lists") or []
        )
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["text"]).strip(),
            apply_url=job["hostedUrl"],
            posted_at=epoch_ms(job.get("createdAt")),
            location_text="; ".join(p for p in places if p) or None,
            country_hint=job.get("country") or None,
            workplace_type=WORKPLACE.get(str(job.get("workplaceType") or "")),
            employment_type=(job.get("categories") or {}).get("commitment"),
            departments=[
                name for name in (categories.get("department"), categories.get("team")) if name
            ],
            salary=salary(pay.get("min"), pay.get("max"), pay.get("currency"), pay.get("interval")),
            description_html=join_html(job.get("description"), sections, job.get("additional")),
        )
