"""HiBob (Bob) career pages: GET https://{company}.careers.hibob.com/api/job-ad
with the request header ``companyIdentifier: {company}``, which the public
career page itself sends, returns {"jobAdDetails": [...]} with full
descriptions and pay transparency fields."""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import as_url, iso_datetime, join_html, salary
from erio_core.connectors.base import Fetcher, FetchResponse, header_getter
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
WORKPLACE: dict[str, RemoteStatus] = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


class HiBobConnector(PagedJsonConnector):
    slug = "hibob"
    hosts = frozenset({"*.careers.hibob.com"})

    def list_url(self, board_token: str, page: int) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a HiBob company subdomain: {board_token!r}")
        return f"https://{board_token}.careers.hibob.com/api/job-ad"

    def fetch_page(self, fetcher: Fetcher, board_token: str, page: int) -> FetchResponse:
        url = self.list_url(board_token, page)
        return header_getter(fetcher).get_with(url, {"companyIdentifier": board_token})

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["jobAdDetails"])

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        places = [p for p in dict.fromkeys([job.get("site"), job.get("country")]) if p]
        workspace = str(job.get("workspaceTypeId") or "").lower().replace("-", "")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            apply_url=as_url(f"https://{raw.board_token}.careers.hibob.com/jobs/{raw.external_id}"),
            posted_at=iso_datetime(job.get("publishedAt")),
            location_text=", ".join(places) or None,
            country_hint=job.get("country") or None,
            workplace_type=WORKPLACE.get(workspace),
            employment_type=job.get("employmentType"),
            departments=[d] if (d := job.get("department")) else [],
            salary=salary(
                job.get("payTransparencyMinSalary"),
                job.get("payTransparencyMaxSalary"),
                job.get("payTransparencySalaryCurrency"),
                job.get("payTransparencySalaryPayPeriod"),
            ),
            description_html=join_html(
                job.get("description"),
                job.get("responsibilities"),
                job.get("requirements"),
                job.get("benefits"),
            ),
        )
