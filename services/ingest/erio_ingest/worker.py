"""Celery application for crawl work.

Start a worker with ``celery -A erio_ingest.worker worker``.
"""

import random
from datetime import datetime
from functools import lru_cache
from typing import Any

from celery import Celery, Task
from redis import Redis
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from erio_core.connectors import CONNECTORS
from erio_core.search.index import client as search_client
from erio_core.settings import get_settings
from erio_ingest.dedup import dedup_all
from erio_ingest.discovery import discover_boards
from erio_ingest.fetcher import PoliteFetcher
from erio_ingest.fx import FX_HOSTS, refresh_rates
from erio_ingest.indexer import rebuild, sync_changed
from erio_ingest.normalizer import BATCH, latest_rates, normalize_pending
from erio_ingest.pipeline import crawl_board, utcnow
from erio_ingest.ratelimit import HostRateLimiter
from erio_ingest.scheduler import schedule_due_boards
from erio_ingest.smoke import smoke_test_sources
from erio_ingest.status import mark_unverified
from erio_ingest.storage import S3RawStore

settings = get_settings()

app = Celery("erio_ingest", broker=settings.redis_url, backend=settings.redis_url)
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="crawl",
    result_expires=3600,
    timezone="UTC",
    # Celery beat (`celery -A erio_ingest.worker beat`) queues due boards every minute.
    beat_schedule={
        "schedule-due-boards": {"task": "erio.schedule_due_boards", "schedule": 60.0},
        "mark-unverified-jobs": {"task": "erio.mark_unverified_jobs", "schedule": 600.0},
        "normalize-pending": {"task": "erio.normalize_pending", "schedule": 300.0},
        "refresh-fx-rates": {"task": "erio.refresh_fx_rates", "schedule": 6 * 3600.0},
        "index-changed": {"task": "erio.index_changed", "schedule": 20.0},
        "rebuild-index": {"task": "erio.rebuild_index", "schedule": 24 * 3600.0},
        "discover-boards": {"task": "erio.discover_boards", "schedule": 24 * 3600.0},
        "smoke-test-sources": {"task": "erio.smoke_test_sources", "schedule": 24 * 3600.0},
        "dedup-all": {"task": "erio.dedup_all", "schedule": 24 * 3600.0},
    },
)

# Three attempts in all for timeouts, 429s and 5xx (spec section 5).
MAX_RETRIES = 2


@lru_cache
def engine() -> Engine:
    return create_engine(settings.sqlalchemy_url, pool_pre_ping=True)


@lru_cache
def fetcher() -> PoliteFetcher:
    hosts = {host for connector in CONNECTORS.values() for host in connector.hosts}
    limiter = HostRateLimiter(Redis.from_url(settings.redis_url), settings.crawl_rate_per_host)
    return PoliteFetcher(hosts, limiter, settings)


@lru_cache
def fx_fetcher() -> PoliteFetcher:
    limiter = HostRateLimiter(Redis.from_url(settings.redis_url), settings.crawl_rate_per_host)
    return PoliteFetcher(FX_HOSTS, limiter, settings)


@lru_cache
def store() -> S3RawStore:
    return S3RawStore(settings)


def backoff_seconds(retries: int) -> float:
    """Exponential backoff with jitter: about 30s, then 60s."""
    return 30.0 * 2.0**retries + random.uniform(0, 10)  # noqa: S311 (jitter, not security)


@app.task(name="erio.ping")
def ping() -> str:
    return "pong"


@app.task(name="erio.schedule_due_boards", ignore_result=True)
def schedule_due_boards_task() -> int:
    queued = schedule_due_boards(
        engine(), lambda board_id: crawl_board_task.delay(board_id), utcnow()
    )
    return len(queued)


@app.task(name="erio.mark_unverified_jobs", ignore_result=True)
def mark_unverified_jobs_task() -> int:
    with Session(engine()) as session, session.begin():
        return mark_unverified(session, utcnow())


@app.task(name="erio.refresh_fx_rates", ignore_result=True)
def refresh_fx_rates_task() -> dict[str, int]:
    return refresh_rates(engine(), fx_fetcher())


@app.task(name="erio.normalize_pending", ignore_result=True)
def normalize_pending_task() -> dict[str, Any]:
    with Session(engine()) as session:
        have_rates = bool(latest_rates(session))
    if not have_rates:
        refresh_fx_rates_task()
    result = normalize_pending(engine(), store(), utcnow)
    if result.jobs == BATCH:
        normalize_pending_task.delay()  # more waiting: keep going
    if result.jobs:
        index_changed_task.delay()
    return {
        "jobs": result.jobs,
        "needs_review": result.needs_review,
        "merged": result.merged,
        "failed": result.failed[:20],
    }


@app.task(name="erio.dedup_all", ignore_result=True)
def dedup_all_task() -> dict[str, Any]:
    """The nightly full pass; each normalizer batch already dedups its own jobs."""
    result = dedup_all(engine(), utcnow)
    if result.merges:
        index_changed_task.delay()
    return {"checked": result.checked, "merged": len(result.merges), "seconds": result.seconds}


# How far the indexer has read jobs.updated_at; losing it only means one full sync.
WATERMARK_KEY = "erio:indexer:watermark"


@app.task(name="erio.index_changed", ignore_result=True)
def index_changed_task() -> dict[str, int]:
    redis = Redis.from_url(settings.redis_url)
    raw = redis.get(WATERMARK_KEY)
    since = datetime.fromisoformat(raw.decode()) if isinstance(raw, bytes) else None
    result = sync_changed(engine(), search_client(), settings.search_alias, since)
    if result.watermark is not None:
        redis.set(WATERMARK_KEY, result.watermark.isoformat())
    return {"indexed": result.indexed, "removed": result.removed}


@app.task(name="erio.rebuild_index", ignore_result=True)
def rebuild_index_task() -> dict[str, Any]:
    name, count = rebuild(engine(), search_client(), settings.search_alias)
    return {"index": name, "jobs": count}


@app.task(name="erio.discover_boards", ignore_result=True)
def discover_boards_task() -> dict[str, Any]:
    result = discover_boards(engine(), fetcher(), utcnow)
    return {"tried": result.tried, "found": result.found}


@app.task(name="erio.smoke_test_sources", ignore_result=True)
def smoke_test_sources_task() -> dict[str, bool]:
    return {check.source: check.ok for check in smoke_test_sources(engine(), fetcher(), utcnow)}


@app.task(name="erio.crawl_board", bind=True, max_retries=MAX_RETRIES)
def crawl_board_task(self: Task, board_id: int) -> dict[str, Any]:
    result = crawl_board(engine(), board_id, fetcher(), store())
    if result.retryable and self.request.retries < MAX_RETRIES:
        raise self.retry(countdown=backoff_seconds(self.request.retries))
    if result.new_postings or result.changed_postings:
        normalize_pending_task.delay()
    return {
        "board_id": board_id,
        "run_id": result.run_id,
        "outcome": result.outcome,
        "http_status": result.http_status,
        "postings_seen": result.postings_seen,
        "new_postings": result.new_postings,
        "changed_postings": result.changed_postings,
        "closed_postings": result.closed_postings,
    }
