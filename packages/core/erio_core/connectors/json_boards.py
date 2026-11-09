"""Job-board software and ATS platforms with a public JSON list:

- JobKit          https://{board}/jobs.json?page={n}      (Markdown descriptions)
- Jobboardly      https://{board}/jobs.json               (every job in one response)
- WP Job Manager  https://{site}/wp-json/wp/v2/job-listings?per_page=100&page={n}
- JOIN            https://join.com/api/public/companies/{id}/jobs?page={n}&pageSize=5

Boards on their own domain are registered by address: the token is
``https://{host}`` (JOIN: ``{companyId}/{slug}``).
"""

import html
import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector, base_url
from erio_core.connectors._util import (
    as_url,
    iso_datetime,
    markdown_to_html,
    numbers_in,
    salary,
)
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

ARRANGEMENT: dict[str, RemoteStatus] = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


class JobKitConnector(PagedJsonConnector):
    slug = "jobkit"
    hosts = frozenset({"*.jobkit.io"})

    def list_url(self, board_token: str, page: int) -> str:
        return f"{base_url(board_token)}/jobs.json?page={page}"

    def items(self, data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, list):
            raise ValueError("a JobKit board answers with a list of jobs")
        return data

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return bool(items)

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        amounts = numbers_in(job.get("salary"))
        low = amounts[0] if amounts else None
        high = amounts[1] if len(amounts) > 1 else low
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("company"),
            apply_url=job["url"],
            posted_at=iso_datetime(job.get("created_at")),
            location_text=job.get("location") or None,
            workplace_type=ARRANGEMENT.get(str(job.get("arrangement") or "").lower()),
            employment_type=(job.get("term") or {}).get("name"),
            departments=[c] if (c := (job.get("category") or {}).get("name")) else [],
            salary=salary(low, high or low, job.get("salary_currency"), job.get("salary_period")),
            description_html=markdown_to_html(job.get("description")),
        )


class JobboardlyConnector(PagedJsonConnector):
    slug = "jobboardly"
    hosts = frozenset({"*.jobboardly.com"})

    def list_url(self, board_token: str, page: int) -> str:
        return f"{base_url(board_token)}/jobs.json"

    def items(self, data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, list):
            raise ValueError("a Jobboardly board answers with a list of jobs")
        return data

    def item_id(self, item: dict[str, Any]) -> str:
        match = re.search(r"-([0-9a-f]{6,})$", (item.get("links") or {}).get("self", ""))
        if not match:
            raise ValueError("a Jobboardly job without a link")
        return match.group(1)

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        company = job.get("company") or {}
        pay = job.get("salary") or {}
        mode = str(job.get("location") or "").lower()
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=company.get("name"),
            apply_url=job["links"]["self"],
            posted_at=iso_datetime(job.get("published_at")),
            location_text=company.get("location") or None,
            workplace_type=ARRANGEMENT.get(mode),
            employment_type=job.get("arrangement"),
            salary=salary(pay.get("minimum"), pay.get("maximum"), None, pay.get("schedule")),
            description_html=(job.get("description") or {}).get("html"),
        )


class WPJobManagerConnector(PagedJsonConnector):
    """WordPress sites running WP Job Manager; token ``https://{site}``. A page
    past the last answers 400."""

    slug = "wp_job_manager"
    hosts = frozenset()
    past_last_page = frozenset({400, 404})
    per_page = 100

    def list_url(self, board_token: str, page: int) -> str:
        return (
            f"{base_url(board_token)}/wp-json/wp/v2/job-listings"
            f"?per_page={self.per_page}&page={page}"
        )

    def items(self, data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, list):
            raise ValueError("a WordPress site answers with a list of job listings")
        return data

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return len(items) >= self.per_page

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        meta: dict[str, Any] = job["meta"] if isinstance(job.get("meta"), dict) else {}
        extra: dict[str, Any] = job["all_meta"] if isinstance(job.get("all_meta"), dict) else {}

        def pick(key: str) -> Any:
            """``meta`` as WordPress registers it, else the site's ``all_meta`` (lists)."""
            if meta.get(key) not in (None, "", []):
                return meta[key]
            listed = extra.get(key)
            return (listed[0] if isinstance(listed, list) and listed else listed) or None

        title = html.unescape((job.get("title") or {}).get("rendered") or "").strip()
        pay = " ".join(
            str(p) for p in (meta.get("_job_salary"), meta.get("_job_salary_currency")) if p
        )
        description = (job.get("content") or {}).get("rendered") or None
        if meta.get("_job_salary") and description:
            description = f"<p>Salary: {html.escape(pay)}</p>{description}"
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=title,
            company_name=pick("_company_name"),
            apply_url=job["link"],
            posted_at=iso_datetime(job.get("date_gmt") and f"{job['date_gmt']}+00:00"),
            # Sites that geocode listings (SportyJob) also give the town and country.
            location_text=pick("geolocation_formatted_address") or pick("_job_location"),
            city=pick("geolocation_city"),
            country_hint=pick("geolocation_country_short"),
            workplace_type="remote" if str(pick("_remote_position")) == "1" else None,
            description_html=description,
        )


class JoinConnector(PagedJsonConnector):
    """JOIN. The token is "{companyId}/{slug}" (the page is join.com/companies/{slug});
    the list carries no description. Amounts are in cents."""

    slug = "join"
    hosts = frozenset({"join.com"})
    page_size = 5

    def list_url(self, board_token: str, page: int) -> str:
        match = re.fullmatch(r"(\d{1,10})/([a-z0-9][a-z0-9-]{0,80})", board_token)
        if not match:
            raise ValueError(f"not a JOIN token (companyId/slug): {board_token!r}")
        return (
            f"https://join.com/api/public/companies/{match[1]}/jobs"
            f"?page={page}&pageSize={self.page_size}"
        )

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["items"])

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return page < int((data.get("pagination") or {}).get("pageCount") or 0)

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        city = job.get("city") or {}
        country = job.get("country") or {}
        low = job.get("salaryAmountFrom") or {}
        high = job.get("salaryAmountTo") or {}
        shown = (job.get("settings") or {}).get("showSalary")
        slug = raw.board_token.split("/", 1)[1]
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            apply_url=as_url(f"https://join.com/companies/{slug}/{job['idParam']}"),
            posted_at=iso_datetime(job.get("createdAt")),
            location_text=", ".join(
                p for p in (city.get("cityName"), city.get("regionName"), country.get("name")) if p
            ) or None,
            city=city.get("cityName"),
            region=city.get("regionName"),
            country_hint=country.get("iso3166"),
            workplace_type=ARRANGEMENT.get(str(job.get("workplaceType") or "").lower()),
            employment_type=(job.get("employmentType") or {}).get("name"),
            departments=[c] if (c := (job.get("category") or {}).get("name")) else [],
            salary=salary(
                float(low["amount"]) / 100 if low.get("amount") else None,
                float(high["amount"]) / 100 if high.get("amount") else None,
                low.get("currency"),
                job.get("salaryFrequency"),
            ) if shown else None,
        )  # fmt: skip
