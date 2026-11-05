"""Workable public jobs widget.

GET https://apply.workable.com/api/v1/widget/accounts/{account}?details=true
returns the account's name and {"jobs": [...]}, no authentication needed.
An unknown account answers 404.
"""

import json

from erio_core.connectors._util import iso_datetime
from erio_core.connectors.base import Connector
from erio_core.schemas import PartialJob, RawPosting

API = "https://apply.workable.com/api/v1/widget/accounts"


class WorkableConnector(Connector):
    slug = "workable"
    hosts = frozenset({"apply.workable.com"})

    def board_url(self, board_token: str) -> str:
        return f"{API}/{board_token}?details=true"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        jobs = data["jobs"]
        if not isinstance(jobs, list):
            raise ValueError("'jobs' is not a list")
        if not data.get("name"):
            raise ValueError("no account name: not a Workable account")
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["shortcode"]),
                payload={**job, "company_name": data["name"]},
            )
            for job in jobs
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        places = [
            ", ".join(
                p for p in (place.get("city"), place.get("region"), place.get("country")) if p
            )
            for place in job.get("locations") or []
            if not place.get("hidden")
        ]
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("company_name"),
            apply_url=job.get("url") or job["shortlink"],
            posted_at=iso_datetime(job.get("published_on") or job.get("created_at")),
            location_text="; ".join(p for p in places if p) or None,
            city=job.get("city") or None,
            region=job.get("state") or None,
            country_hint=job.get("country") or None,
            # Workable only says whether a role can be done remotely.
            workplace_type="remote" if job.get("telecommuting") else None,
            departments=[name for name in (job.get("department"), job.get("function")) if name],
            description_html=job.get("description") or None,
        )
