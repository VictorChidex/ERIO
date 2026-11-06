"""ApplicantPro and iSolvedHire (one platform, two brands): public JSON job lists.

- list:   GET https://{sub}.{domain}/core/jobs/{domainId}?getParams={"isInternal":0}
          every job in one response, in data.jobs
- detail: GET https://{sub}.{domain}/jobs/{id}, whose JobPosting JSON-LD has the description

The board token is "{sub}/{domainId}": the subdomain and the numeric ``domainId``
printed in the HTML of https://{sub}.{domain}/jobs/ ("domainId : 3465"). Internal
postings are never requested (robots.txt disallows those routes).
"""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import as_url, iso_datetime, salary
from erio_core.connectors.base import BoardFetch, Fetcher, FetchError
from erio_core.connectors.jsonld import job_postings
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"([A-Za-z0-9][A-Za-z0-9-]{0,62})/(\d{1,9})")
PARAMS = "%7B%22isInternal%22%3A0%7D"
WORKPLACE: dict[str, RemoteStatus] = {
    "fully remote": "remote", "remote": "remote", "hybrid": "hybrid", "onsite": "onsite",
    "on-site": "onsite",
}  # fmt: skip


def _parts(board_token: str) -> tuple[str, str]:
    match = TOKEN.fullmatch(board_token)
    if not match:
        raise ValueError(f"not a board token (subdomain/domainId): {board_token!r}")
    return match[1].lower(), match[2]


class ApplicantProConnector(PagedJsonConnector):
    max_details = 150

    def __init__(self, slug: str, domain: str):
        self.slug = slug
        self.domain = domain
        self.hosts = frozenset({f"*.{domain}"})

    def list_url(self, board_token: str, page: int) -> str:
        sub, domain_id = _parts(board_token)
        return f"https://{sub}.{self.domain}/core/jobs/{domain_id}?getParams={PARAMS}"

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["data"]["jobs"])

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        fetched = super().list_postings(fetcher, board_token, etag)
        sub, _ = _parts(board_token)
        for raw in fetched.postings[: self.max_details]:
            try:
                response = fetcher.get(f"https://{sub}.{self.domain}/jobs/{raw.external_id}")
                found = job_postings(response.body.decode("utf-8", "replace"))
            except FetchError:
                continue
            if response.status == 200 and found:
                raw.payload["posting"] = found[0]
        return fetched

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        sub, _ = _parts(raw.board_token)
        posting = job.get("posting") or {}
        organization = posting.get("hiringOrganization")
        company = organization.get("name") if isinstance(organization, dict) else None
        city = (job.get("city") or "").strip() or None
        region = job.get("abbreviation") or job.get("stateName") or None
        country = job.get("iso3")
        place = ", ".join(p for p in (city, region, country) if p)
        department = job.get("orgTitle")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=company,
            apply_url=as_url(job.get("jobUrl") or f"https://{sub}.{self.domain}/jobs/{job['id']}"),
            posted_at=iso_datetime(posting.get("datePosted")) if posting else None,
            location_text=place or None,
            city=city,
            region=region,
            country_hint=country,
            workplace_type=WORKPLACE.get(str(job.get("workplaceType") or "").lower()),
            employment_type=job.get("employmentType"),
            departments=[department] if department else [],
            salary=salary(
                job.get("minSalary"), job.get("maxSalary"), "USD", job.get("payTypeFrame")
            ),
            description_html=posting.get("description"),
        )
