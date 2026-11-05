"""GET /v1/jobs and GET /v1/jobs/{canonical_id} (spec section 7)."""

import re
from datetime import datetime
from typing import Annotated, Any, get_args

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import RedirectResponse
from opensearchpy import OpenSearch
from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_api.access import rate_limit
from erio_api.deps import engine, run_search, search_alias, search_client
from erio_api.errors import ApiError
from erio_api.search import BadCursor, JobQuery, Sort, build_search, read_results
from erio_core.db.models import Company, Job, JobSource, RawPosting
from erio_core.schemas import JobRecord, JobStatus, RemoteStatus, RoleCategory

router = APIRouter(prefix="/v1", tags=["jobs"], dependencies=[Depends(rate_limit)])

COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")


class Facets(BaseModel):
    country: dict[str, int]
    role: dict[str, int]
    remote_status: dict[str, int]


class JobsMeta(BaseModel):
    total: int
    next_cursor: str | None
    facets: Facets


class JobsPage(BaseModel):
    data: list[JobRecord]
    meta: JobsMeta


class JobDetail(BaseModel):
    data: JobRecord


def _codes(raw: str | None) -> list[str]:
    codes = [c.strip().upper() for c in (raw or "").split(",") if c.strip()]
    bad = [c for c in codes if not COUNTRY_CODE.match(c)]
    if bad:
        raise ApiError(400, "invalid_parameter", f"country: not ISO 3166-1 alpha-2 codes: {bad}")
    return codes


def _list(raw: str | None) -> list[str]:
    return [v.strip().lower() for v in (raw or "").split(",") if v.strip()]


def _check(values: list[str], allowed: tuple[str, ...], name: str) -> list[str]:
    unknown = sorted(set(values) - set(allowed))
    if unknown:
        raise ApiError(400, "invalid_parameter", f"{name}: unknown values {unknown}")
    return values


@router.get("/jobs", response_model=JobsPage, summary="Search and filter jobs")
def search_jobs(
    search: Annotated[OpenSearch, Depends(search_client)],
    alias: Annotated[str, Depends(search_alias)],
    q: Annotated[str | None, Query(max_length=200, description="Words to find")] = None,
    country: Annotated[
        str | None, Query(description="ISO 3166-1 alpha-2 codes, comma-separated, e.g. NG,CA")
    ] = None,
    include_worldwide: Annotated[bool, Query(description="Include worldwide-remote roles")] = True,
    remote_status: Annotated[str | None, Query(description="remote, hybrid, onsite")] = None,
    role: Annotated[str | None, Query(description="Role categories, comma-separated")] = None,
    salary_min_usd: Annotated[int | None, Query(ge=0, description="Minimum yearly USD")] = None,
    platform: Annotated[str | None, Query(description="Source slugs, comma-separated")] = None,
    posted_after: Annotated[datetime | None, Query(description="ISO 8601")] = None,
    status: Annotated[str, Query(description="open, unknown")] = "open",
    sort: Annotated[Sort, Query()] = "recent",
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    per_page: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    query = JobQuery(
        q=q.strip() if q and q.strip() else None,
        countries=_codes(country),
        include_worldwide=include_worldwide,
        remote_status=_check(_list(remote_status), get_args(RemoteStatus), "remote_status"),
        roles=_check(_list(role), get_args(RoleCategory), "role"),
        salary_min_usd=salary_min_usd,
        platforms=_list(platform),
        posted_after=posted_after,
        status=_check(_list(status) or ["open"], get_args(JobStatus), "status"),
        sort=sort,
        cursor=cursor,
        per_page=per_page,
    )
    try:
        body = build_search(query)
    except BadCursor as error:
        raise ApiError(400, "invalid_cursor", str(error)) from error
    return read_results(run_search(search, alias, body), per_page)


@router.get(
    "/jobs/{canonical_id}",
    response_model=JobDetail,
    summary="One job, with its full description",
    responses={301: {"description": "The job was merged into another; follow Location"}},
)
def get_job(
    canonical_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,40}$")],
    db: Annotated[Engine, Depends(engine)],
) -> Any:
    with Session(db) as session:
        merged_into = session.scalar(
            select(Job.merged_into).where(Job.canonical_id == canonical_id)
        )
        if merged_into is not None:
            return RedirectResponse(f"/v1/jobs/{merged_into}", status_code=301)
        row = session.execute(
            select(Job, Company)
            .join(Company, Company.id == Job.company_id)
            .where(Job.canonical_id == canonical_id, Job.review_reason.is_(None))
        ).one_or_none()
        if row is None:
            raise ApiError(404, "not_found", f"no job {canonical_id}")
        job, company = row
        # The primary posting's source first: it is where apply_url leads.
        sources = session.scalars(
            select(RawPosting.source_slug)
            .join(JobSource, JobSource.raw_posting_id == RawPosting.id)
            .where(JobSource.job_id == canonical_id)
            .order_by(JobSource.is_primary.desc(), RawPosting.source_slug)
        ).all()
        # The jobs row holds every JobRecord field except company and sources.
        columns = {
            name: getattr(job, name) for name in JobRecord.model_fields if hasattr(job, name)
        }
        record = JobRecord.model_validate(
            columns
            | {
                "company": {
                    "name": company.name,
                    "domain": company.domain,
                    "logo_url": company.logo_url,
                },
                "sources": list(dict.fromkeys(sources)),
            }
        )
    return {"data": record}
