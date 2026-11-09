"""Merge canonical jobs that are one real job (spec section 6).

Every raw posting first becomes its own job (exact-ID pass: the same source
and external ID always update that one posting). Dedup then compares each
job with the other live jobs of its company using ``erio_core.dedup.match``
and merges a duplicate into the job that ranks first: an ATS posting over a
board posting, then the earliest ``posted_at``, then the earliest ``indexed_at``.

A merge moves the loser's postings to the survivor, records the method and
time on each moved link, and points the loser at the survivor. The loser
leaves search and its ID redirects; the survivor lists every source.
Merges are kept when a posting changes later (decision D-16).

``dedup_jobs`` runs on each normalizer batch. ``dedup_all`` checks every live
job, nightly and from the command line; ``recent_merges`` lists what was
merged, for the admin merge view:

    python -m erio_ingest.dedup          # full pass
    python -m erio_ingest.dedup merges   # the 50 latest merges
"""

import sys
import time
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, Select, func, or_, select, update
from sqlalchemy.orm import Session

from erio_core.db.models import Job, JobSource, RawPosting, Source
from erio_core.dedup import MAX_DISTANCE, DedupMethod, Fingerprint, hamming, match, simhash
from erio_ingest.history import record_event
from erio_ingest.status import refresh_jobs

# Looser methods sort later; a job records the loosest one that built it.
METHOD_ORDER = ("exact_id", "exact_key", "simhash")
FINGERPRINT_BATCH = 500
MERGE_BATCH = 50


@dataclass(frozen=True)
class Candidate:
    """A live job as dedup sees it: its fingerprint and how it ranks."""

    canonical_id: str
    fingerprint: Fingerprint
    key: str
    rank: tuple[Any, ...]


@dataclass
class DedupResult:
    checked: int = 0
    fingerprinted: int = 0
    merges: list[tuple[str, str, DedupMethod]] = field(default_factory=list)
    seconds: float = 0.0


def fingerprint(job: Job) -> Fingerprint:
    return Fingerprint(
        company_id=job.company_id,
        title=job.title,
        city=job.city,
        country_code=job.country_code,
        remote_scope=job.remote_scope,
        apply_url=job.apply_url,
        simhash=job.simhash,
        region=job.region,
        eligible=frozenset(job.eligible_country_codes or ()),
    )


def _candidates() -> Select[Any]:
    """Live jobs with their fingerprint columns and the kind of their primary source."""
    kind = (
        select(Source.kind)
        .join(RawPosting, RawPosting.source_slug == Source.slug)
        .join(JobSource, JobSource.raw_posting_id == RawPosting.id)
        .where(JobSource.job_id == Job.canonical_id, JobSource.is_primary)
        .limit(1)
        .scalar_subquery()
    )
    return select(Job, kind.label("kind")).where(
        Job.merged_into.is_(None), Job.dedup_key.is_not(None)
    )


def _candidate(job: Job, kind: str | None) -> Candidate:
    far_future = datetime.max.replace(tzinfo=UTC)
    rank = (
        kind != "ats",
        job.posted_at or far_future,
        job.indexed_at,
        job.canonical_id,
    )
    return Candidate(job.canonical_id, fingerprint(job), job.dedup_key or "", rank)


def _first_match(
    job: Candidate, others: Iterable[Candidate]
) -> tuple[Candidate, DedupMethod] | None:
    """The best-ranked other job that ``job`` duplicates, with the pass that found it."""
    found = []
    for other in others:
        if other.canonical_id == job.canonical_id:
            continue
        a, b = job.fingerprint.simhash, other.fingerprint.simhash
        # Cheap checks first; ``match`` then applies every rule.
        close = a is not None and b is not None and hamming(a, b) <= MAX_DISTANCE
        if job.key != other.key and not close:
            continue
        method = match(job.fingerprint, other.fingerprint)
        if method is not None:
            found.append((other, method))
    return min(found, key=lambda pair: pair[0].rank) if found else None


def merge(session: Session, loser: str, winner: str, method: DedupMethod, now: datetime) -> None:
    """Move every posting of ``loser`` to ``winner`` and retire ``loser``."""
    session.flush()
    session.execute(
        update(JobSource)
        .where(JobSource.job_id == loser)
        .values(
            job_id=winner,
            is_primary=False,
            dedup_method=func.coalesce(JobSource.dedup_method, method),
            merged_at=func.coalesce(JobSource.merged_at, now),
        )
        .execution_options(synchronize_session=False)
    )
    session.execute(
        update(Job)
        .where(or_(Job.canonical_id == loser, Job.merged_into == loser))
        .values(merged_into=winner, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    methods = session.scalars(
        select(JobSource.dedup_method).where(
            JobSource.job_id == winner, JobSource.dedup_method.is_not(None)
        )
    ).all()
    session.execute(
        update(Job)
        .where(Job.canonical_id == winner)
        .values(
            dedup_method=max(methods, key=METHOD_ORDER.index) if methods else None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    session.expire_all()
    record_event(session, winner, "merged", now)
    refresh_jobs(session, [winner], now)


def _merge_pair(
    session: Session, job: Candidate, other: Candidate, method: DedupMethod, now: datetime
) -> tuple[str, str, DedupMethod]:
    winner, loser = (other, job) if other.rank <= job.rank else (job, other)
    merge(session, loser.canonical_id, winner.canonical_id, method, now)
    return loser.canonical_id, winner.canonical_id, method


def dedup_jobs(session: Session, job_ids: Collection[str], now: datetime) -> DedupResult:
    """Compare each of these jobs with its company's live jobs; merge duplicates."""
    result = DedupResult()
    for job_id in job_ids:
        row = session.execute(_candidates().where(Job.canonical_id == job_id)).one_or_none()
        if row is None:
            continue
        job = _candidate(row.Job, row.kind)
        result.checked += 1
        same_place = Job.country_code.is_not_distinct_from(job.fingerprint.country_code)
        others = [
            _candidate(other.Job, other.kind)
            for other in session.execute(
                _candidates().where(
                    Job.company_id == job.fingerprint.company_id,
                    or_(Job.dedup_key == job.key, same_place),
                )
            )
        ]
        found = _first_match(job, others)
        if found is not None:
            result.merges.append(_merge_pair(session, job, found[0], found[1], now))
    return result


def survivor(session: Session, job_id: str) -> str:
    """The live job a (possibly merged) job ID now stands for."""
    merged_into = session.scalar(select(Job.merged_into).where(Job.canonical_id == job_id))
    return merged_into or job_id


def fill_fingerprints(engine: Engine) -> int:
    """Fingerprint jobs built before dedup existed.

    ``updated_at`` is kept: a fingerprint changes nothing the index shows.
    """
    filled = 0
    while True:
        with Session(engine) as session, session.begin():
            jobs = session.scalars(
                select(Job).where(Job.dedup_key.is_(None)).limit(FINGERPRINT_BATCH)
            ).all()
            for job in jobs:
                found = replace(fingerprint(job), simhash=simhash(job.description_text))
                session.execute(
                    update(Job)
                    .where(Job.canonical_id == job.canonical_id)
                    .values(dedup_key=found.key(), simhash=found.simhash, updated_at=job.updated_at)
                    .execution_options(synchronize_session=False)
                )
        filled += len(jobs)
        if len(jobs) < FINGERPRINT_BATCH:
            return filled


def dedup_all(engine: Engine, now: Callable[[], datetime]) -> DedupResult:
    """Check every live job against the others of its company and country.

    Matching reads one snapshot; merges are then applied in short
    transactions, each stamped when it runs, so the search indexer (which
    follows ``updated_at`` with a 60-second overlap) never misses one.
    """
    started = time.perf_counter()
    result = DedupResult(fingerprinted=fill_fingerprints(engine))
    with Session(engine) as session:
        jobs = sorted(
            (_candidate(row.Job, row.kind) for row in session.execute(_candidates())),
            key=lambda job: job.rank,
        )
    result.checked = len(jobs)
    # Best-ranked first, so every job is compared only with better-ranked
    # survivors and a match always merges it into one of them.
    found_merges: list[tuple[str, str, DedupMethod]] = []
    by_key: dict[str, list[Candidate]] = defaultdict(list)
    by_place: dict[tuple[int, str | None], list[Candidate]] = defaultdict(list)
    for job in jobs:
        place = (job.fingerprint.company_id, job.fingerprint.country_code)
        found = _first_match(job, by_key[job.key] + by_place[place])
        if found is not None:
            found_merges.append((job.canonical_id, found[0].canonical_id, found[1]))
            continue
        by_key[job.key].append(job)
        by_place[place].append(job)
    for start in range(0, len(found_merges), MERGE_BATCH):
        with Session(engine) as session, session.begin():
            for loser, winner, method in found_merges[start : start + MERGE_BATCH]:
                # The normalizer may have merged either job since the snapshot.
                live = session.scalars(
                    select(Job.canonical_id).where(
                        Job.canonical_id.in_((loser, winner)), Job.merged_into.is_(None)
                    )
                ).all()
                if len(live) == 2:
                    merge(session, loser, winner, method, now())
                    result.merges.append((loser, winner, method))
    result.seconds = time.perf_counter() - started
    return result


@dataclass(frozen=True)
class MergeRecord:
    merged_at: datetime
    method: str
    job_id: str
    title: str
    source: str
    external_id: str


def recent_merges(engine: Engine, limit: int = 50) -> list[MergeRecord]:
    """The latest postings dedup moved onto another job, newest first."""
    with Session(engine) as session:
        rows = session.execute(
            select(
                JobSource.merged_at,
                JobSource.dedup_method,
                Job.canonical_id,
                Job.title,
                RawPosting.source_slug,
                RawPosting.external_id,
            )
            .join(Job, Job.canonical_id == JobSource.job_id)
            .join(RawPosting, RawPosting.id == JobSource.raw_posting_id)
            .where(JobSource.merged_at.is_not(None))
            .order_by(JobSource.merged_at.desc(), JobSource.raw_posting_id)
            .limit(limit)
        )
        return [
            MergeRecord(merged_at, method, job_id, title, source, external_id)
            for merged_at, method, job_id, title, source, external_id in rows
            if merged_at is not None and method is not None
        ]


def main() -> None:
    from sqlalchemy import create_engine

    from erio_core.settings import get_settings

    engine = create_engine(get_settings().sqlalchemy_url)
    if sys.argv[1:] == ["merges"]:
        for record in recent_merges(engine):
            print(
                f"{record.merged_at:%Y-%m-%d %H:%M}  {record.method:9}  {record.job_id}  "
                f"{record.title[:50]:50}  <- {record.source}:{record.external_id}"
            )
        return
    result = dedup_all(engine, lambda: datetime.now(UTC))
    methods: dict[str, int] = defaultdict(int)
    for _, _, method in result.merges:
        methods[method] += 1
    print(
        f"checked {result.checked} live jobs ({result.fingerprinted} newly fingerprinted) "
        f"in {result.seconds:.1f}s; merged {len(result.merges)}: {dict(methods)}"
    )


if __name__ == "__main__":
    main()
