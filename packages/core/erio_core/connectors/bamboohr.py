"""BambooHR careers pages: GET https://{company}.bamboohr.com/careers/list lists
open jobs ({"meta", "result": [...]}) without descriptions; GET
.../careers/{id}/detail adds the description, posting date, compensation and
full address. Customers use the subdomain; an unknown one redirects away."""

import html
import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import as_url, iso_datetime
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
# locationType: 0 on site, 1 remote, 2 hybrid.
WORKPLACE: dict[str, RemoteStatus] = {"0": "onsite", "1": "remote", "2": "hybrid"}


class BambooHRConnector(PagedJsonConnector):
    slug = "bamboohr"
    hosts = frozenset({"*.bamboohr.com"})

    def list_url(self, board_token: str, page: int) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a BambooHR company subdomain: {board_token!r}")
        return f"https://{board_token}.bamboohr.com/careers/list"

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["result"])

    def detail_url(self, board_token: str, item: dict[str, Any]) -> str | None:
        return f"https://{board_token}.bamboohr.com/careers/{item['id']}/detail"

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        detail = ((job.get("detail") or {}).get("result") or {}).get("jobOpening") or {}
        place = detail.get("location") or job.get("location") or {}
        city, state = place.get("city"), place.get("state")
        country = place.get("addressCountry")
        pay = detail.get("compensation")
        description = detail.get("description")
        if pay and description:
            description = f"<p>Compensation: {html.escape(str(pay))}</p>{description}"
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["jobOpeningName"]).strip(),
            apply_url=as_url(
                detail.get("jobOpeningShareUrl")
                or f"https://{raw.board_token}.bamboohr.com/careers/{raw.external_id}"
            ),
            posted_at=iso_datetime(detail.get("datePosted")),
            location_text=", ".join(p for p in (city, state, country) if p) or None,
            city=city or None,
            region=state or None,
            country_hint=country or None,
            workplace_type=WORKPLACE.get(str(job.get("locationType")))
            or ("remote" if job.get("isRemote") else None),
            employment_type=job.get("employmentStatusLabel"),
            departments=[d] if (d := job.get("departmentLabel")) else [],
            description_html=description,
        )
