"""Exenzo job boards (jobboardsoftware.com): Nuxt sites over a public JSON API.

    https://{api-host}/api/public/v1/job-boards/{jobBoardId}/jobs?page={n}&limit=100

The board token is ``https://{api-host}/{jobBoardId}``; the API host is in the
page's ``baseApiUrl`` (``greenjobs.api.exenzo.com``, or a board's own host
such as ``api.vacatures.co``) and the id is usually 1. The list carries full
descriptions. Jobs take the employer in ``organisation_name``.
"""

import html
import re
from typing import Any
from urllib.parse import urlsplit

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import as_url, iso_datetime, join_html, salary
from erio_core.schemas import PartialJob, RawPosting

PAGE_SIZE = 100
EURO = frozenset({"NL", "BE", "DE", "FR", "LU", "IE", "AT", "ES", "IT", "PT", "FI"})
EMPLOYMENT = ("dienstverband", "contract", "time")
FIELD = ("vakgebied", "category")


def _names(job: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    segments = job.get("segments_names")
    if not isinstance(segments, dict):
        return []
    for key in keys:
        if names := [str(n) for n in segments.get(key) or [] if n]:
            return names
    return []


class ExenzoConnector(PagedJsonConnector):
    slug = "exenzo"
    hosts = frozenset({"*.api.exenzo.com"})
    max_pages = 100

    def list_url(self, board_token: str, page: int) -> str:
        parts = urlsplit(board_token)
        match = re.fullmatch(r"/(\d{1,6})", parts.path)
        if parts.scheme != "https" or not parts.hostname or not match:
            raise ValueError(f"not an Exenzo token (https://{{api-host}}/{{id}}): {board_token!r}")
        return (
            f"https://{parts.hostname}/api/public/v1/job-boards/{match[1]}/jobs"
            f"?page={page}&limit={PAGE_SIZE}"
        )

    def items(self, data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ValueError("an Exenzo board answers with {total, data: [...]}")
        return list(data["data"])

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return page < int(data.get("lastPage") or 0)

    def item_id(self, item: dict[str, Any]) -> str:
        return str(item.get("uuid") or item["id"])

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        urls = job.get("job_boards_url")
        page = next(iter(urls.values()), None) if isinstance(urls, dict) else None
        country = job.get("country_code")
        employment = _names(job, EMPLOYMENT)
        place = job.get("location_name") or job.get("city")
        platform = job.get("text_platform")
        body = job.get("text_own")
        if not body and isinstance(platform, dict):
            body = join_html(*(str(v) for v in platform.values()))
        if not body and job.get("description"):
            body = f"<p>{html.escape(job['description'])}</p>"
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("organisation_name") or None,
            apply_url=as_url(page or job.get("job_url") or job["apply_url"]),
            posted_at=iso_datetime(job.get("from") or job.get("created_at")),
            location_text=place or None,
            city=job.get("city") or None,
            country_hint=country,
            workplace_type="remote" if job.get("remote") else None,
            employment_type=", ".join(employment) or None,
            departments=_names(job, FIELD),
            salary=salary(
                job.get("salary_min"),
                job.get("salary_max"),
                "EUR" if country in EURO else None,
                job.get("salary_type"),
            ),
            description_html=body or None,
        )
