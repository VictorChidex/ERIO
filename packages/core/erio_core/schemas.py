"""Shared job types used by ingest and the API (spec sections 4 and 5).

The pipeline moves a job through three shapes:

- ``RawPosting``: one posting exactly as a source returned it.
- ``PartialJob``: what a connector's ``parse`` could read from it, before
  normalization (country, remote scope, salary in USD, role).
- ``JobRecord``: the canonical job the API returns.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    computed_field,
    field_validator,
)

RoleCategory = Literal[
    "engineering", "product", "design", "data", "operations", "sales", "marketing",
    "healthcare", "education", "hospitality", "retail", "logistics", "trades", "security",
    "other",
]  # fmt: skip
RemoteStatus = Literal["remote", "hybrid", "onsite"]
RemoteScope = Literal["country", "region", "worldwide"]
SalaryPeriod = Literal["year", "month", "hour"]
EmploymentType = Literal[
    "full_time", "part_time", "contract", "temporary", "internship", "volunteer"
]  # fmt: skip
JobStatus = Literal["open", "closed", "unknown"]
DedupMethod = Literal["exact_id", "exact_key", "simhash"]


def content_hash(payload: dict[str, Any]) -> str:
    """SHA-256 of a payload in canonical JSON form, so key order never matters."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RawPosting(BaseModel):
    """One posting as a source reported it, with its untouched payload."""

    model_config = ConfigDict(frozen=True)

    source_slug: str
    board_token: str
    external_id: str
    payload: dict[str, Any]
    fetched_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content_hash(self) -> str:
        return content_hash(self.payload)


class SalaryHint(BaseModel):
    """Salary as the source states it, in the posted currency and period."""

    min: int | None = None
    max: int | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    period: SalaryPeriod | None = None
    text: str | None = None


class PartialJob(BaseModel):
    """Everything ``parse`` can read from one raw posting, before normalization.

    Location fields are hints: the normalizer resolves the final country,
    remote scope and eligible countries from them (spec section 6).
    """

    source_slug: str
    external_id: str
    title: str
    company_name: str | None = None
    apply_url: HttpUrl
    posted_at: AwareDatetime | None = None
    location_text: str | None = None
    city: str | None = None
    region: str | None = None
    country_hint: str | None = None
    workplace_type: RemoteStatus | None = None
    # As the source words it ("Full-time", "FULL_TIME", "Contract"); the
    # normalizer maps it to an EmploymentType.
    employment_type: str | None = None
    departments: list[str] = Field(default_factory=list)
    salary: SalaryHint | None = None
    description_html: str | None = None

    @field_validator("apply_url", mode="before")
    @classmethod
    def apply_links_are_https(cls, value: Any) -> Any:
        """Candidates are sent only to https pages; sites redirect an http link there."""
        if isinstance(value, str) and value.strip()[:7].lower() == "http://":
            return "https://" + value.strip()[7:]
        return value


class Company(BaseModel):
    name: str
    domain: str | None = None
    logo_url: str | None = None


class JobRecord(BaseModel):
    """A canonical job, exactly as ``GET /v1/jobs`` returns it (spec section 4)."""

    canonical_id: str
    title: str
    company: Company
    role_category: RoleCategory
    location_text: str | None
    city: str | None
    region: str | None
    country_code: str | None = Field(
        description="ISO 3166-1 alpha-2; null only for worldwide-remote roles"
    )
    lat: float | None
    lon: float | None
    remote_status: RemoteStatus
    remote_scope: RemoteScope | None = Field(description="Remote roles only")
    employment_type: EmploymentType | None = Field(
        default=None, description="Null when the source does not say"
    )
    eligible_country_codes: list[str] = Field(
        description="Countries a remote role accepts; empty means worldwide"
    )
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    salary_period: SalaryPeriod | None
    salary_usd_annual_min: int | None = Field(
        description="Converted with that day's FX rate; for filtering and sorting only"
    )
    status: JobStatus
    posted_at: AwareDatetime | None
    indexed_at: AwareDatetime
    last_verified_at: AwareDatetime | None
    closed_at: AwareDatetime | None
    # Every source that lists the job; the primary posting's (apply_url's) first.
    sources: list[str]
    dedup_method: DedupMethod | None
    apply_url: str
    description_html: str | None
    description_text: str | None
