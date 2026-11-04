"""Celery application for crawl work.

Start a worker with ``celery -A erio_ingest.worker worker``. Connectors and the
crawl schedule arrive in step 4; for now the worker only answers ``ping``.
"""

from celery import Celery

from erio_core.settings import get_settings

settings = get_settings()

app = Celery("erio_ingest", broker=settings.redis_url, backend=settings.redis_url)
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="crawl",
    timezone="UTC",
)


@app.task(name="erio.ping")
def ping() -> str:
    return "pong"
