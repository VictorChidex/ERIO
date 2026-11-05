"""Turn raw postings into canonical jobs (spec section 6).

Picks up every raw posting whose current content has not been normalized
yet, reads its stored payload, lets its connector parse it, normalizes it,
and upserts the job built from it. A new posting's job is then checked for
duplicates and may merge into another (erio_ingest.dedup). Job status then
follows the postings through the status rules.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

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
from erio_ingest.storage import RawStore

BATCH = 200


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
    with Session(engine) as session, session.begin():
        rates = latest_rates(session)
        pending = session.execute(
            select(RawPosting, CompanyBoard)
            .join(CompanyBoard, CompanyBoard.id == RawPosting.board_id)
            .where(
                RawPosting.payload_s3_key.is_not(None),
                RawPosting.normalized_hash.is_distinct_from(RawPosting.content_hash),
            )
            .order_by(RawPosting.id)
            .limit(limit)
            .with_for_update(of=RawPosting, skip_locked=True)
        ).all()

        job_ids = []
        for posting, board in pending:
            try:
                # A savepoint per posting: a failure rolls back only that posting.
                with session.begin_nested():
                    job_id = _normalize_one(session, posting, board, store, rates, now())
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


def _normalize_one(
    session: Session,
    posting: RawPosting,
    board: CompanyBoard,
    store: RawStore,
    rates: dict[str, float],
    now: datetime,
) -> str:
    connector = get_connector(posting.source_slug)
    raw = RawPostingData(
        source_slug=posting.source_slug,
        board_token=board.board_token,
        external_id=posting.external_id,
        payload=store.get_posting(str(posting.payload_s3_key)),
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
