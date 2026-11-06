"""Paylocity career pages: GET https://recruiting.paylocity.com/recruiting/jobs/All/{guid}
embeds every open job as ``window.pageData`` (title, place, publish date, a
110-character description). Each job's page, /Recruiting/Jobs/Details/{JobId}, has
the JobPosting JSON-LD with the full description, employment type and pay.

The board token is the company GUID in the careers-page address. A crawl reads at
most ``max_details`` job pages and reports a larger board as an incomplete fetch.
"""

import json
import re
from typing import Any

from erio_core.connectors._util import as_url, iso_datetime, salary
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.connectors.jsonld import job_postings
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
MARKER = "window.pageData = "
DETAILS = "https://recruiting.paylocity.com/Recruiting/Jobs/Details"


def _guid(board_token: str) -> str:
    token = board_token.lower()
    if not TOKEN.fullmatch(token):
        raise ValueError(f"not a Paylocity company GUID: {board_token!r}")
    return token


class PaylocityConnector(Connector):
    slug = "paylocity"
    hosts = frozenset({"recruiting.paylocity.com"})
    max_details = 150

    def board_url(self, board_token: str) -> str:
        return f"https://recruiting.paylocity.com/recruiting/jobs/All/{_guid(board_token)}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        text = body.decode("utf-8", "replace")
        start = text.find(MARKER)
        if start < 0:
            raise ValueError("the page carries no job data")
        data, _ = json.JSONDecoder().raw_decode(text, start + len(MARKER))
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["JobId"]),
                payload=job,
            )
            for job in data["Jobs"]
            if not job.get("IsInternal")
        ]

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        fetched = super().list_postings(fetcher, board_token, etag)
        for raw in fetched.postings[: self.max_details]:
            try:
                response = fetcher.get(f"{DETAILS}/{raw.external_id}")
                found = job_postings(response.body.decode("utf-8", "replace"))
            except FetchError:
                continue
            if response.status == 200 and found:
                raw.payload["posting"] = found[0]
        if len(fetched.postings) > self.max_details:
            return BoardFetch(
                fetched.postings, fetched.http_status, fetched.body, fetched.etag, complete=False
            )
        return fetched

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        posting: dict[str, Any] = job.get("posting") or {}
        place = job.get("JobLocation") or {}
        city = place.get("City") or job.get("LocationName")
        organization = posting.get("hiringOrganization")
        pay = posting.get("baseSalary")
        value = (pay.get("value") if isinstance(pay, dict) else None) or {}
        kinds = posting.get("employmentType")
        kind = ", ".join(kinds) if isinstance(kinds, list) else kinds
        department = job.get("HiringDepartment")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["JobTitle"]).strip(),
            company_name=organization.get("name") if isinstance(organization, dict) else None,
            apply_url=as_url(f"{DETAILS}/{raw.external_id}"),
            posted_at=iso_datetime(job.get("PublishedDate")),
            location_text=", ".join(p for p in (city, place.get("State")) if p) or None,
            city=city or None,
            region=place.get("State") or None,
            country_hint=place.get("Country") or None,
            workplace_type="remote" if job.get("IsRemote") else None,
            employment_type=kind or None,
            departments=[department] if department else [],
            salary=salary(
                value.get("minValue"),
                value.get("maxValue"),
                pay.get("currency") if isinstance(pay, dict) else None,
                value.get("unitText"),
            ),
            description_html=posting.get("description") or job.get("Description"),
        )
