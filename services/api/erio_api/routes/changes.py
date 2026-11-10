"""GET /v1/changes and /v1/export/jobs: following the index without re-reading it.

The change feed answers "what happened since I last looked": jobs added, changed,
closed, reopened or merged, in the order they happened, each with a cursor so a
client that polls never reads the same event twice and never misses one.

The export is the whole open index as gzipped newline-delimited JSON, one job per
line, in a stable order so an interrupted download can resume from the last job it
saw. Both leave out the long description: ``GET /v1/jobs/{id}`` has it.
"""

import json
import zlib
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_api.access import rate_limit
from erio_api.deps import engine
from erio_core.db.models import JOB_EVENT_KINDS, Company, Job, JobEvent

router = APIRouter(prefix="/v1", tags=["changes"], dependencies=[Depends(rate_limit)])

CHANGE_PAGE = 500
CHANGE_PAGE_MAX = 1000
EXPORT_BATCH = 2000
Cursor = Annotated[
    int | None,
    Query(ge=0, description="The next_cursor of the previous page; omit to start from the oldest"),
]


class ChangedJob(BaseModel):
    canonical_id: str
    title: str
    company: str
    company_slug: str | None
    status: str
    country_code: str | None
    city: str | None
    apply_url: str


class Change(BaseModel):
    event_id: int
    at: datetime
    kind: str = Field(description="added, changed, closed, reopened or merged")
    changes: dict[str, Any] = Field(description="For 'changed': each field as [old, new]")
    job: ChangedJob


class ChangePage(BaseModel):
    items: list[Change]
    next_cursor: int = Field(
        description="Pass as cursor to continue; unchanged when there was nothing new"
    )
    has_more: bool


@router.get("/changes", response_model=ChangePage, summary="Jobs added, changed or closed")
def changes(
    db: Annotated[Engine, Depends(engine)],
    cursor: Cursor = None,
    since: Annotated[
        datetime | None,
        Query(description="Start at the first event at or after this time (ignored with cursor)"),
    ] = None,
    kind: Annotated[list[str] | None, Query(description="Only these kinds of event")] = None,
    limit: Annotated[int, Query(ge=1, le=CHANGE_PAGE_MAX)] = CHANGE_PAGE,
) -> ChangePage:
    after = cursor or 0
    statement = (
        select(JobEvent, Job, Company)
        .join(Job, Job.canonical_id == JobEvent.job_id)
        .join(Company, Company.id == Job.company_id)
        .where(JobEvent.id > after)
        .order_by(JobEvent.id)
        .limit(limit + 1)
    )
    if cursor is None and since is not None:
        statement = statement.where(JobEvent.at >= since)
    wanted = [k for k in (kind or []) if k in JOB_EVENT_KINDS]
    if wanted:
        statement = statement.where(JobEvent.kind.in_(wanted))
    with Session(db) as session:
        rows = session.execute(statement).tuples().all()
    page = rows[:limit]
    items = [
        Change(
            event_id=event.id,
            at=event.at,
            kind=event.kind,
            changes=event.changes,
            job=ChangedJob(
                canonical_id=job.canonical_id,
                title=job.title,
                company=company.name,
                company_slug=company.slug,
                status=job.status,
                country_code=job.country_code,
                city=job.city,
                apply_url=job.apply_url,
            ),
        )
        for event, job, company in page
    ]
    return ChangePage(
        items=items,
        next_cursor=items[-1].event_id if items else after,
        has_more=len(rows) > limit,
    )


def _line(job: Job, company: Company) -> bytes:
    record = {
        "canonical_id": job.canonical_id,
        "title": job.title,
        "company": company.name,
        "company_slug": company.slug,
        "company_domain": company.domain,
        "role_category": job.role_category,
        "location_text": job.location_text,
        "city": job.city,
        "region": job.region,
        "country_code": job.country_code,
        "remote_status": job.remote_status,
        "remote_scope": job.remote_scope,
        "employment_type": job.employment_type,
        "eligible_country_codes": job.eligible_country_codes,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "salary_period": job.salary_period,
        "salary_unreliable": job.salary_unreliable,
        "status": job.status,
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        "last_verified_at": job.last_verified_at.isoformat() if job.last_verified_at else None,
        "apply_url": job.apply_url,
    }
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def export_stream(
    db: Engine, country: str | None, after: str | None, limit: int | None
) -> Iterator[bytes]:
    """Open jobs in canonical_id order as one gzip stream, a batch at a time."""
    statement = (
        select(Job, Company)
        .join(Company, Company.id == Job.company_id)
        .where(Job.status == "open", Job.merged_into.is_(None))
        .order_by(Job.canonical_id)
    )
    if country:
        statement = statement.where(Job.country_code == country.upper())
    if after:
        statement = statement.where(Job.canonical_id > after)
    if limit:
        statement = statement.limit(limit)
    compressor = zlib.compressobj(wbits=31)  # 16 + 15: a gzip container
    with Session(db) as session:
        result = session.execute(statement.execution_options(yield_per=EXPORT_BATCH))
        for job, company in result.tuples():
            chunk = compressor.compress(_line(job, company))
            if chunk:
                yield chunk
    yield compressor.flush()


@router.get(
    "/export/jobs",
    summary="Every open job as gzipped NDJSON",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/gzip": {}}}},
)
def export_jobs(
    db: Annotated[Engine, Depends(engine)],
    country: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    after: Annotated[
        str | None, Query(max_length=40, description="Resume after this canonical_id")
    ] = None,
    limit: Annotated[int | None, Query(ge=1, le=1_000_000)] = None,
) -> StreamingResponse:
    return StreamingResponse(
        export_stream(db, country, after, limit),
        media_type="application/gzip",
        headers={"Content-Disposition": 'attachment; filename="erio-jobs.ndjson.gz"'},
    )
