"""Turn raw postings into canonical jobs (spec section 6).

Picks up every raw posting whose current content has not been normalized
yet, reads its stored payload (before any transaction opens, so a stalled object store
never holds locks), lets its connector parse it, normalizes it,
and upserts the job built from it. A new posting's job is then checked for
duplicates and may merge into another (erio_ingest.dedup). Job status then
follows the postings through the status rules.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from erio_core.connectors import get_connector
from erio_core.db.models import CompanyBoard, FxRate, Job, JobSource, RawPosting
from erio_core.dedup import Fingerprint, simhash
from erio_core.normalize.job import normalize
from erio_core.schemas import RawPosting as RawPostingData
from erio_ingest.dedup import dedup_jobs, survivor
from erio_ingest.status import refresh_jobs
from erio_ingest.storage import STORE_WORKERS, RawStore

BATCH = 200
# Payloads are read STORE_WORKERS at a time. When a whole group of at least
# MIN_GROUP_TO_CALL_DOWN reads fails, object storage is treated as down: the batch stops and
# the next scheduled run tries again, instead of waiting out every posting in turn.
MIN_GROUP_TO_CALL_DOWN = 3


@dataclass
class NormalizeResult:
    jobs: int = 0
    needs_review: int = 0
    merged: int = 0
    failed: list[str] = field(default_factory=list)


def latest_rates(session: Session) -> dict[str, float]:
    """The most recent rate for every currency (US dollars per unit)."""
    newest = (
        select(FxRate.currency, func.max(FxRate.day).label("day"))
        .group_by(FxRate.currency)
        .subquery()
    )
    rows = session.execute(
        select(FxRate.currency, FxRate.usd_per_unit).join(
            newest, (FxRate.currency == newest.c.currency) & (FxRate.day == newest.c.day)
        )
    )
    return {currency: rate for currency, rate in rows}


def normalize_pending(
    engine: Engine, store: RawStore, now: Callable[[], datetime], limit: int = BATCH
) -> NormalizeResult:
    result = NormalizeResult()
    # Read the stored payloads first, with no transaction open: a slow or stalled object
    # store must never hold row locks that other writers queue behind.
    payloads = _read_payloads(engine, store, limit, result)
    if not payloads:
        return result
    with Session(engine) as session, session.begin():
        rates = latest_rates(session)
        pending = session.execute(
            select(RawPosting, CompanyBoard)
            .join(CompanyBoard, CompanyBoard.id == RawPosting.board_id)
            .where(
                RawPosting.id.in_(list(payloads)),
                RawPosting.normalized_hash.is_distinct_from(RawPosting.content_hash),
            )
            .order_by(RawPosting.id)
            .with_for_update(of=RawPosting, skip_locked=True)
        ).all()

        job_ids = []
        for posting, board in pending:
            try:
                # A savepoint per posting: a failure rolls back only that posting.
                with session.begin_nested():
                    job_id = _normalize_one(
                        session, posting, board, payloads[posting.id], rates, now()
                    )
            except Exception as error:
                result.failed.append(
                    f"{posting.source_slug}:{posting.external_id}: {error!r}"[:300]
                )
                continue
            job_ids.append(job_id)
            posting.normalized_hash = posting.content_hash

        session.flush()
        result.jobs = len(job_ids)
        result.merged = len(dedup_jobs(session, job_ids, now()).merges)
        job_ids = sorted({survivor(session, job_id) for job_id in job_ids})
        refresh_jobs(session, job_ids, now())
        result.needs_review = (
            session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.canonical_id.in_(job_ids), Job.review_reason.is_not(None))
            )
            or 0
        )
    return result


def _read_payloads(
    engine: Engine, store: RawStore, limit: int, result: NormalizeResult
) -> dict[int, dict[str, Any]]:
    """The stored payloads of the next postings to normalize, by posting id.

    Read in small parallel groups: one at a time, object storage latency adds up to
    minutes per batch. A payload that cannot be read is reported as a failure and its
    posting stays pending, so the next run tries it again; a whole group failing means
    storage is down, and the batch stops there.
    """
    with Session(engine) as session:
        wanted = session.execute(
            select(
                RawPosting.id,
                RawPosting.source_slug,
                RawPosting.external_id,
                RawPosting.payload_s3_key,
            )
            .where(
                RawPosting.payload_s3_key.is_not(None),
                RawPosting.normalized_hash.is_distinct_from(RawPosting.content_hash),
            )
            .order_by(RawPosting.id)
            .limit(limit)
        ).all()

    def read(item: Any) -> tuple[int, dict[str, Any] | None, str | None]:
        posting_id, source_slug, external_id, key = item
        try:
            return posting_id, store.get_posting(str(key)), None
        except Exception as error:
            return posting_id, None, f"{source_slug}:{external_id}: {error!r}"[:300]

    payloads: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(STORE_WORKERS) as pool:
        for start in range(0, len(wanted), STORE_WORKERS):
            group = list(pool.map(read, wanted[start : start + STORE_WORKERS]))
            failures = [error for _, _, error in group if error]
            for posting_id, payload, error in group:
                if payload is not None and error is None:
                    payloads[posting_id] = payload
            result.failed.extend(failures)
            if len(failures) == len(group) and len(group) >= MIN_GROUP_TO_CALL_DOWN:
                result.failed.append(
                    f"object storage looks down: a whole group of {len(group)} reads failed"
                )
                break
    return payloads


def _normalize_one(
    session: Session,
    posting: RawPosting,
    board: CompanyBoard,
    payload: dict[str, Any],
    rates: dict[str, float],
    now: datetime,
) -> str:
    connector = get_connector(posting.source_slug)
    raw = RawPostingData(
        source_slug=posting.source_slug,
        board_token=board.board_token,
        external_id=posting.external_id,
        payload=payload,
    )
    partial = connector.parse(raw)
    job = normalize(partial, rates)
    fingerprint = Fingerprint(
        company_id=board.company_id,
        title=job.title,
        city=job.location.city,
        country_code=job.location.country_code,
        remote_scope=job.location.remote_scope,
        apply_url=job.apply_url,
        simhash=simhash(job.description_text),
        region=job.location.region,
        eligible=frozenset(job.location.eligible_country_codes),
    )
    values = job.columns() | {
        "company_id": board.company_id,
        "dedup_key": fingerprint.key(),
        "simhash": fingerprint.simhash,
        # A new version of the posting: the AI fallback looks at it afresh
        # (its earlier answers come back from the cache when nothing changed).
        "ai_checked_at": None,
        "ai_filled": [],
        "posted_at": partial.posted_at,
        "indexed_at": now,
        "updated_at": now,
        "last_verified_at": posting.last_seen_at,
    }
    statement = insert(Job).values(values)
    updates = {key: statement.excluded[key] for key in values if key != "canonical_id"}
    session.execute(
        statement.on_conflict_do_update(index_elements=[Job.canonical_id], set_=updates)
    )
    session.execute(
        insert(JobSource)
        .values(job_id=job.canonical_id, raw_posting_id=posting.id, is_primary=True)
        .on_conflict_do_nothing()
    )
    # After a merge the posting belongs to the surviving job.
    return survivor(session, job.canonical_id)
