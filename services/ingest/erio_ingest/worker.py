"""Celery application for crawl work.

Start a worker with ``celery -A erio_ingest.worker worker``.
"""

import random
from datetime import datetime
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import httpx
from celery import Celery, Task, signals
from redis import Redis
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_core import live
from erio_core.ai import Gateway, default_routing
from erio_core.ai.store import PostgresStore
from erio_core.connectors import CONNECTORS
from erio_core.db.engine import make_engine
from erio_core.db.models import CompanyBoard
from erio_core.observability import bind, configure_logging, setup_tracing
from erio_core.search.index import client as search_client
from erio_core.settings import get_settings
from erio_ingest.ai_fallback import BATCH as AI_BATCH
from erio_ingest.ai_fallback import fill_with_ai
from erio_ingest.archive_discovery import RedisState, discover_from_archive
from erio_ingest.dedup import dedup_all
from erio_ingest.discovery import discover_boards
from erio_ingest.fetcher import PoliteFetcher
from erio_ingest.fx import FX_HOSTS, refresh_rates
from erio_ingest.indexer import rebuild, sync_changed
from erio_ingest.normalizer import latest_rates, normalize_pending
from erio_ingest.pipeline import crawl_board, utcnow
from erio_ingest.ratelimit import HostRateLimiter
from erio_ingest.saved_searches import cleanup_workspaces, email_digests, evaluate_saved_searches
from erio_ingest.scheduler import schedule_due_boards
from erio_ingest.smoke import smoke_test_sources
from erio_ingest.status import mark_unverified
from erio_ingest.storage import RawStore, make_store

settings = get_settings()

app = Celery("erio_ingest", broker=settings.redis_url, backend=settings.redis_url)


@signals.setup_logging.connect
def _logging(**_: Any) -> None:
    """JSON logs (erio_core.observability) instead of Celery's own format."""
    configure_logging("worker")


@signals.worker_process_init.connect
def _tracing(**_: Any) -> None:
    if setup_tracing("worker"):
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]
        SQLAlchemyInstrumentor().instrument()
        HTTPXClientInstrumentor().instrument()


@signals.task_prerun.connect
def _task_context(task_id: str | None = None, task: Task | None = None, **_: Any) -> None:
    bind(task=getattr(task, "name", None), task_id=task_id)


app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="crawl",
    # Turning crawled postings into searchable jobs runs on its own queue and worker: behind
    # a hundred board crawls (some take minutes) it would wait for hours.
    task_routes={
        "erio.normalize_pending": {"queue": "pipeline"},
        "erio.index_changed": {"queue": "pipeline"},
        "erio.evaluate_saved_searches": {"queue": "pipeline"},
        "erio.cleanup_workspaces": {"queue": "pipeline"},
        "erio.email_digests": {"queue": "pipeline"},
    },
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
        "discover-from-archive": {"task": "erio.discover_from_archive", "schedule": 6 * 3600.0},
        "smoke-test-sources": {"task": "erio.smoke_test_sources", "schedule": 24 * 3600.0},
        "dedup-all": {"task": "erio.dedup_all", "schedule": 24 * 3600.0},
        "ai-fallback": {"task": "erio.ai_fallback", "schedule": 300.0},
        "ai-eval": {"task": "erio.ai_eval", "schedule": 24 * 3600.0},
        "evaluate-saved-searches": {"task": "erio.evaluate_saved_searches", "schedule": 600.0},
        "cleanup-workspaces": {"task": "erio.cleanup_workspaces", "schedule": 24 * 3600.0},
        "email-digests": {"task": "erio.email_digests", "schedule": 3600.0},
    },
)

# Three attempts in all for timeouts, 429s and 5xx (spec section 5).
MAX_RETRIES = 2


@lru_cache
def engine() -> Engine:
    return make_engine(settings)


def board_hosts() -> set[str]:
    """Hosts of boards registered by full URL: feeds, career sites on an
    employer's own domain, job boards on their own domain (spec section 9:
    only hosts registered in company_boards)."""
    with Session(engine()) as session:
        tokens = session.scalars(
            select(CompanyBoard.board_token).where(CompanyBoard.board_token.like("https://%"))
        )
        return {host for token in tokens if (host := urlsplit(token).hostname)}


@lru_cache
def fetcher() -> PoliteFetcher:
    hosts = {host for connector in CONNECTORS.values() for host in connector.hosts}
    limiter = HostRateLimiter(Redis.from_url(settings.redis_url), settings.crawl_rate_per_host)
    return PoliteFetcher(hosts, limiter, settings, extra_hosts=board_hosts)


@lru_cache
def archive_fetcher() -> PoliteFetcher:
    """Reads the Internet Archive's CDX index, a request every other second, patiently."""
    limiter = HostRateLimiter(Redis.from_url(settings.redis_url), settings.archive_rate_per_s)
    client = httpx.Client(timeout=settings.archive_timeout_s, follow_redirects=False)
    return PoliteFetcher(frozenset({"web.archive.org"}), limiter, settings, client=client)


@lru_cache
def fx_fetcher() -> PoliteFetcher:
    limiter = HostRateLimiter(Redis.from_url(settings.redis_url), settings.crawl_rate_per_host)
    return PoliteFetcher(FX_HOSTS, limiter, settings)


@lru_cache
def store() -> RawStore:
    return make_store(settings)


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
    if result.jobs:
        normalize_pending_task.delay()  # progress was made: keep going until nothing moves
    if result.jobs:
        index_changed_task.delay()
    return {
        "jobs": result.jobs,
        "needs_review": result.needs_review,
        "merged": result.merged,
        "failed": result.failed[:20],
    }


@lru_cache
def gateway() -> Gateway:
    """The AI gateway; locally it reaches only the self-hosted model (D-17).

    No model serves a task until it passes that task's evaluation gate.
    """
    return Gateway(
        default_routing(), PostgresStore(engine()), enabled=settings.ai_enabled, approved={}
    )


@app.task(name="erio.ai_fallback", ignore_result=True)
def ai_fallback_task() -> dict[str, Any]:
    from erio_ingest.ai_eval import approved_models

    gate = gateway()
    gate.approved = approved_models(engine(), gate.routing)
    result = fill_with_ai(engine(), gate, utcnow)
    if result.looked_at == AI_BATCH and result.checked:
        ai_fallback_task.delay()  # more waiting, and models are answering
    if result.filled:
        index_changed_task.delay()
    return {"looked_at": result.looked_at, "checked": result.checked, "filled": dict(result.filled)}


@app.task(name="erio.ai_eval", ignore_result=True)
def ai_eval_task() -> list[dict[str, Any]]:
    """Nightly: every usable model against 100 rows of each labeled set."""
    from erio_ingest.ai_eval import run

    return [vars(score) for score in run(engine(), gateway(), limit=100)]


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
    redis.set(WATERMARK_KEY, result.watermark.isoformat())
    return {"indexed": result.indexed, "removed": result.removed}


@app.task(name="erio.evaluate_saved_searches", ignore_result=True)
def evaluate_saved_searches_task() -> dict[str, int]:
    """Every 10 minutes: new matches for each saved search, then their webhooks."""
    result = evaluate_saved_searches(
        engine(), search_client(), settings.search_alias, settings.site_url, utcnow()
    )
    return {
        "searches": result.searches,
        "new_matches": result.new_matches,
        "webhooks_sent": result.webhooks_sent,
        "webhooks_failed": result.webhooks_failed,
        "errors": result.errors,
    }


@app.task(name="erio.email_digests", ignore_result=True)
def email_digests_task() -> dict[str, int]:
    """Hourly: email the new CV-matched jobs to each confirmed address that is due."""
    result = email_digests(
        engine(), search_client(), settings.search_alias, settings.site_url, utcnow()
    )
    return {
        "checked": result.checked,
        "sent": result.sent,
        "jobs": result.jobs,
        "failed": result.failed,
    }


@app.task(name="erio.cleanup_workspaces", ignore_result=True)
def cleanup_workspaces_task() -> int:
    """Daily: delete workspaces nobody has used for 12 months."""
    return cleanup_workspaces(engine(), utcnow())


@app.task(name="erio.rebuild_index", ignore_result=True)
def rebuild_index_task() -> dict[str, Any]:
    name, count = rebuild(engine(), search_client(), settings.search_alias)
    return {"index": name, "jobs": count}


@app.task(name="erio.discover_boards", ignore_result=True)
def discover_boards_task() -> dict[str, Any]:
    result = discover_boards(engine(), fetcher(), utcnow)
    return {"tried": result.tried, "found": result.found}


@app.task(name="erio.discover_from_archive", ignore_result=True)
def discover_from_archive_task() -> dict[str, Any]:
    result = discover_from_archive(
        engine(),
        archive_fetcher(),
        fetcher(),
        RedisState(Redis.from_url(settings.redis_url)),
        utcnow,
    )
    return {
        "pages": result.pages,
        "candidates": result.candidates,
        "probed": result.probed,
        "found": {source: len(tokens) for source, tokens in result.found.items()},
        "errors": result.errors[:5],
    }


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


@app.task(name=live.TASK, ignore_result=True)
def crawl_board_live_task(board_id: int, refresh_id: str) -> dict[str, Any]:
    """Read one board now, for a user's search, and make what it found searchable.

    Runs on the ``live`` queue so it never waits behind the steady crawl. It normalizes and
    indexes inline instead of queueing those steps behind that crawl, and it never retries:
    a board that fails is counted as done and the steady crawl will try it again.
    """
    new = changed = 0
    try:
        result = crawl_board(engine(), board_id, fetcher(), store())
        new, changed = result.new_postings, result.changed_postings
        if new or changed:
            normalize_pending(engine(), store(), utcnow)
            index_changed_task()
    finally:
        live.board_done(Redis.from_url(settings.redis_url), refresh_id, new, changed)
    return {"board_id": board_id, "new_postings": new, "changed_postings": changed}
