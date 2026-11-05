"""Ashby public job posting API.

GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true
returns {"jobs": [...]}, no authentication needed. An unknown board answers
404; a board with no openings answers an empty list.
"""

import json
from typing import Any

from erio_core.connectors._util import iso_datetime, salary
from erio_core.connectors.base import Connector
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus, SalaryHint

API = "https://api.ashbyhq.com/posting-api/job-board"
WORKPLACE: dict[str, RemoteStatus] = {"Remote": "remote", "Hybrid": "hybrid", "OnSite": "onsite"}


def _salary(compensation: dict[str, Any] | None) -> SalaryHint | None:
    for part in (compensation or {}).get("summaryComponents") or []:
        if part.get("compensationType") == "Salary":
            return salary(
                part.get("minValue"), part.get("maxValue"), part.get("currencyCode"),
                part.get("interval"),
            )  # fmt: skip
    return None


class AshbyConnector(Connector):
    slug = "ashby"
    hosts = frozenset({"api.ashbyhq.com"})

    def board_url(self, board_token: str) -> str:
        return f"{API}/{board_token}?includeCompensation=true"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        jobs = json.loads(body)["jobs"]
        if not isinstance(jobs, list):
            raise ValueError("'jobs' is not a list")
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["id"]),
                payload=job,
            )
            for job in jobs
            # Unlisted postings are reachable only by direct link: not for search.
            if job.get("isListed", True)
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        places = [job.get("location")] + [
            extra.get("location") for extra in job.get("secondaryLocations") or []
        ]
        address = ((job.get("address") or {}).get("postalAddress")) or {}
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            apply_url=job["jobUrl"],
            posted_at=iso_datetime(job.get("publishedAt")),
            location_text="; ".join(p for p in places if p) or None,
            city=address.get("addressLocality") or None,
            region=address.get("addressRegion") or None,
            country_hint=address.get("addressCountry") or None,
            workplace_type=WORKPLACE.get(str(job.get("workplaceType") or "")),
            employment_type=job.get("employmentType"),
            departments=[name for name in (job.get("department"), job.get("team")) if name],
            salary=_salary(job.get("compensation")),
            description_html=job.get("descriptionHtml") or None,
        )
