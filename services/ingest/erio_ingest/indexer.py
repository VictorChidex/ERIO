"""Keep the OpenSearch jobs index in step with Postgres (spec section 7).

``sync_changed`` runs every 20 seconds: it re-reads every job changed since
the last run and indexes or removes it. A row's ``updated_at`` is when its
transaction started, so a change can commit after a sync has read past its
time. Each sync therefore saves as the next starting point the start of the
oldest transaction still open (or the database clock, less a few seconds
for clock skew): anything stamped before that has surely committed. Rows
are read again only while a transaction that could hide them is open.
``rebuild`` fills a fresh index from scratch and swaps the alias, nightly or
on demand, with no downtime.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk
from sqlalchemy import Engine, Integer, Select, func, select, text, update
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import Session

from erio_core.db.models import Company, Job, JobSource, RawPosting
from erio_core.search.index import (
    create_index,
    document,
    ensure_alias,
    new_index_name,
    searchable,
    swap_alias,
)

# Python and database clocks may differ a little; rows this close to the
# saved point are read twice rather than missed.
CLOCK_MARGIN = timedelta(seconds=5)
# Start of the oldest open transaction other than this one, or now.
SAFE_POINT = text(
    """
    select least(now(), coalesce(min(xact_start), now()))
    from pg_stat_activity
    where datname = current_database() and pid <> pg_backend_pid()
      and xact_start is not null and state <> 'idle'
    """
)
PAGE = 1000


@dataclass(frozen=True)
class SyncResult:
    indexed: int
    removed: int
    watermark: datetime


def _rows(statement: Select[Any], engine: Engine) -> Iterator[dict[str, Any]]:
    with Session(engine) as session:
        for row in session.execute(statement).mappings():
            yield dict(row)


def _job_rows() -> Select[Any]:
    # The primary posting's source first: the website names it on the apply button.
    sources = (
        select(
            func.array_agg(
                aggregate_order_by(
                    RawPosting.source_slug, JobSource.is_primary.desc(), RawPosting.source_slug
                )
            )
        )
        .join(JobSource, JobSource.raw_posting_id == RawPosting.id)
        .where(JobSource.job_id == Job.canonical_id)
        .scalar_subquery()
    )
    return select(
        *[column for column in Job.__table__.columns],
        Company.name.label("company_name"),
        Company.domain.label("company_domain"),
        Company.logo_url.label("company_logo_url"),
        sources.label("sources"),
    ).join(Company, Company.id == Job.company_id)


def _actions(rows: Sequence[dict[str, Any]], index: str) -> Iterator[dict[str, Any]]:
    for row in rows:
        if searchable(row):
            yield {
                "_op_type": "index",
                "_index": index,
                "_id": row["canonical_id"],
                "_source": document(row),
            }
        else:
            yield {"_op_type": "delete", "_index": index, "_id": row["canonical_id"]}


def sync_changed(
    engine: Engine, search: OpenSearch, alias: str, since: datetime | None
) -> SyncResult:
    """Index every job changed since ``since`` (all jobs when None).

    The result's watermark is where the next sync should start.
    """
    index = ensure_alias(search, alias)
    with engine.connect() as connection:
        safe_point: datetime = connection.execute(SAFE_POINT).scalar_one() - CLOCK_MARGIN
    statement = _job_rows().order_by(Job.updated_at)
    if since is not None:
        statement = statement.where(Job.updated_at >= since)
    rows = list(_rows(statement, engine))
    indexed = sum(1 for row in rows if searchable(row))
    if rows:
        bulk(search, _actions(rows, index), raise_on_error=False, refresh="wait_for")
        _mark_searchable(engine, rows)
    return SyncResult(indexed, len(rows) - indexed, safe_point)


def _mark_searchable(engine: Engine, rows: Sequence[dict[str, Any]]) -> None:
    """Stamp when each job first became searchable, and how long that took
    from its first sighting (the freshness metric), measured once here.

    ``updated_at`` is kept, or the stamp itself would make the job look changed.
    """
    first = [row["canonical_id"] for row in rows if searchable(row) and not row["searchable_at"]]
    if not first:
        return
    first_seen = (
        select(func.min(RawPosting.first_seen_at))
        .join(JobSource, JobSource.raw_posting_id == RawPosting.id)
        .where(JobSource.job_id == Job.canonical_id)
        .scalar_subquery()
    )
    with Session(engine) as session, session.begin():
        session.execute(
            update(Job)
            .where(Job.canonical_id.in_(first), Job.searchable_at.is_(None))
            .values(
                searchable_at=func.now(),
                freshness_seconds=func.greatest(
                    func.extract("epoch", func.now() - first_seen), 0
                ).cast(Integer),
                updated_at=Job.updated_at,
            )
            .execution_options(synchronize_session=False)
        )


def rebuild(engine: Engine, search: OpenSearch, alias: str) -> tuple[str, int]:
    """Fill a new index with every searchable job, then swap the alias to it."""
    name = new_index_name(alias)
    create_index(search, name)
    rows = [row for row in _rows(_job_rows(), engine) if searchable(row)]
    for start in range(0, len(rows), PAGE):
        bulk(search, _actions(rows[start : start + PAGE], name), refresh=False)
    search.indices.refresh(index=name)
    for old in swap_alias(search, alias, name):
        search.indices.delete(index=old)
    _mark_searchable(engine, rows)
    return name, len(rows)


def count(search: OpenSearch, alias: str) -> int:
    return int(search.count(index=alias)["count"])
