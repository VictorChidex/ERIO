"""A stored job search: the filters of ``GET /v1/jobs`` as validated data.

Saved searches keep these filters as JSON. Turning them into a ``JobQuery`` here keeps one
meaning for every filter, whether a person runs the search or a worker evaluates it.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from erio_core.schemas import EmploymentType, RemoteStatus, RoleCategory
from erio_core.search.query import JobQuery

CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
PlatformSlug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]{1,40}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class SearchParams(BaseModel):
    """Filters a saved search can hold (the same names as the query string of GET /v1/jobs)."""

    model_config = ConfigDict(extra="forbid")

    q: Text | None = None
    country: list[CountryCode] = Field(default_factory=list, max_length=30)
    include_worldwide: bool = True
    remote_status: list[RemoteStatus] = Field(default_factory=list, max_length=3)
    role: list[RoleCategory] = Field(default_factory=list, max_length=15)
    salary_min_usd: int | None = Field(default=None, ge=0, le=10_000_000)
    platform: list[PlatformSlug] = Field(default_factory=list, max_length=20)
    company: Text | None = None
    location: Text | None = None
    employment_type: list[EmploymentType] = Field(default_factory=list, max_length=6)

    def to_query(self, *, indexed_after: datetime | None = None, per_page: int = 25) -> JobQuery:
        return JobQuery(
            q=self.q or None,
            countries=list(self.country),
            include_worldwide=self.include_worldwide,
            remote_status=list(self.remote_status),
            roles=list(self.role),
            salary_min_usd=self.salary_min_usd,
            platforms=list(self.platform),
            company=self.company or None,
            location=self.location or None,
            employment_types=list(self.employment_type),
            indexed_after=indexed_after,
            sort="recent",
            per_page=per_page,
        )
