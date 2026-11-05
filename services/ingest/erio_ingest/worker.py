"""Celery application for crawl work.

Start a worker with ``celery -A erio_ingest.worker worker``.
"""

import random
from functools import lru_cache
from typing import Any

from celery import Celery, Task
from redis import Redis
from sqlalchemy import Engine, create_engine

from erio_core.connectors import CONNECTORS
from erio_core.settings import get_settings
from erio_ingest.fetcher import PoliteFetcher
from erio_ingest.pipeline import crawl_board
from erio_ingest.ratelimit import HostRateLimiter
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
def store() -> S3RawStore:
    return S3RawStore(settings)


def backoff_seconds(retries: int) -> float:
    """Exponential backoff with jitter: about 30s, then 60s."""
    return 30.0 * 2.0**retries + random.uniform(0, 10)  # noqa: S311 (jitter, not security)


@app.task(name="erio.ping")
def ping() -> str:
    return "pong"


@app.task(name="erio.crawl_board", bind=True, max_retries=MAX_RETRIES)
def crawl_board_task(self: Task, board_id: int) -> dict[str, Any]:
    result = crawl_board(engine(), board_id, fetcher(), store())
    if result.retryable and self.request.retries < MAX_RETRIES:
        raise self.retry(countdown=backoff_seconds(self.request.retries))
    return {
        "board_id": board_id,
        "run_id": result.run_id,
        "outcome": result.outcome,
        "http_status": result.http_status,
        "postings_seen": result.postings_seen,
        "new_postings": result.new_postings,
        "changed_postings": result.changed_postings,
    }
