"""Keep the OpenSearch jobs index in step with Postgres (spec section 7).

``sync_changed`` runs every 20 seconds: it re-reads every job changed since
the last run (with a 60-second overlap, because a row's ``updated_at`` is
when its transaction started, which can be before an earlier sync saw the
commit) and indexes or removes it. ``rebuild`` fills a fresh index from
scratch and swaps the alias, nightly or on demand, with no downtime.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk
from sqlalchemy import Engine, Select, func, select
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

OVERLAP = timedelta(seconds=60)
PAGE = 1000


@dataclass(frozen=True)
class SyncResult:
    indexed: int
    removed: int
    watermark: datetime | None


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
    """Index every job changed after ``since`` (all jobs when None)."""
    index = ensure_alias(search, alias)
    statement = _job_rows().order_by(Job.updated_at)
    if since is not None:
        statement = statement.where(Job.updated_at > since - OVERLAP)
    rows = list(_rows(statement, engine))
    if not rows:
        return SyncResult(0, 0, since)
    indexed = sum(1 for row in rows if searchable(row))
    bulk(search, _actions(rows, index), raise_on_error=False, refresh="wait_for")
    return SyncResult(indexed, len(rows) - indexed, max(row["updated_at"] for row in rows))


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
    return name, len(rows)


def count(search: OpenSearch, alias: str) -> int:
    return int(search.count(index=alias)["count"])
