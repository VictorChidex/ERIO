"""Prometheus metrics for the crawl and index pipeline (spec section 10).

Read from Postgres and Redis at each scrape, so they hold across worker
restarts and need no shared counters:

- per source, over the last hour: fetches by outcome (parse errors
  included), success ratio, median and p95 fetch time, postings seen, new,
  closed and reopened; time since the last successful fetch; whether the
  nightly smoke test passed;
- index lag (time since the indexer's last sync point), crawl queue
  backlog, jobs by status, and freshness (first sighting to searchable).

    python -m erio_ingest.metrics     # serves /metrics on port 9108
"""

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY, GaugeMetricFamily
from prometheus_client.registry import Collector
from redis import Redis
from sqlalchemy import Engine, case, func, select
from sqlalchemy.orm import Session

from erio_core.db.models import CompanyBoard, CrawlRun, Job, Source, SourceCheck
from erio_core.freshness import freshness_seconds
from erio_ingest.worker import WATERMARK_KEY

PORT = 9108
WINDOW = timedelta(hours=1)
QUEUE = "crawl"


class PipelineCollector(Collector):
    def __init__(self, engine: Engine, redis: Redis, now: Callable[[], datetime]):
        self.engine = engine
        self.redis = redis
        self.now = now

    def collect(self) -> Iterator[GaugeMetricFamily]:
        now = self.now()
        with Session(self.engine) as session:
            yield from self._sources(session, now)
            yield from self._jobs(session, now)
        yield from self._index_and_queue(now)

    def _sources(self, session: Session, now: datetime) -> Iterator[GaugeMetricFamily]:
        fetches = GaugeMetricFamily(
            "erio_source_fetches",
            "Fetches in the last hour, by outcome",
            labels=["source", "outcome"],
        )
        success = GaugeMetricFamily(
            "erio_source_fetch_success_ratio",
            "Share of fetches in the last hour that succeeded",
            labels=["source"],
        )
        seconds = GaugeMetricFamily(
            "erio_source_fetch_seconds",
            "Fetch time over the last hour",
            labels=["source", "quantile"],
        )
        postings = GaugeMetricFamily(
            "erio_source_postings", "Postings in the last hour's fetches", labels=["source", "kind"]
        )
        since_ok = GaugeMetricFamily(
            "erio_source_seconds_since_success",
            "Time since any board of the source last fetched OK",
            labels=["source"],
        )
        smoke = GaugeMetricFamily(
            "erio_source_smoke_ok", "1 if the latest nightly smoke test passed", labels=["source"]
        )  # fmt: skip

        active = session.scalars(select(Source.slug).where(Source.status != "paused")).all()
        duration = func.extract("epoch", CrawlRun.finished_at - CrawlRun.started_at)
        runs = session.execute(
            select(
                CompanyBoard.source_slug,
                CrawlRun.outcome,
                func.count(),
                func.coalesce(func.sum(CrawlRun.postings_seen), 0),
                func.coalesce(func.sum(CrawlRun.postings_new), 0),
                func.coalesce(func.sum(CrawlRun.postings_closed), 0),
                func.coalesce(func.sum(CrawlRun.postings_reopened), 0),
            )
            .join(CompanyBoard, CompanyBoard.id == CrawlRun.board_id)
            .where(CrawlRun.started_at >= now - WINDOW, CrawlRun.outcome.is_not(None))
            .group_by(CompanyBoard.source_slug, CrawlRun.outcome)
        ).all()
        totals: dict[str, list[int]] = {slug: [0, 0, 0, 0, 0, 0] for slug in active}
        for source, outcome, count, seen, new, closed, reopened in runs:
            fetches.add_metric([source, str(outcome)], count)
            row = totals.setdefault(source, [0, 0, 0, 0, 0, 0])
            row[0] += count
            row[1] += count if outcome == "ok" else 0
            for i, value in enumerate((seen, new, closed, reopened), start=2):
                row[i] += int(value or 0)
        for source, (count, ok, seen, new, closed, reopened) in totals.items():
            if count:
                success.add_metric([source], ok / count)
            for kind, value in (
                ("seen", seen),
                ("new", new),
                ("closed", closed),
                ("reopened", reopened),
            ):
                postings.add_metric([source, kind], value)

        quantiles = session.execute(
            select(
                CompanyBoard.source_slug,
                func.percentile_cont(0.5).within_group(duration),
                func.percentile_cont(0.95).within_group(duration),
            )
            .join(CompanyBoard, CompanyBoard.id == CrawlRun.board_id)
            .where(CrawlRun.started_at >= now - WINDOW, CrawlRun.finished_at.is_not(None))
            .group_by(CompanyBoard.source_slug)
        ).all()
        for source, median, p95 in quantiles:
            seconds.add_metric([source, "0.5"], float(median))
            seconds.add_metric([source, "0.95"], float(p95))

        last_ok = session.execute(
            select(CompanyBoard.source_slug, func.max(CompanyBoard.last_ok_at))
            .where(CompanyBoard.source_slug.in_(active))
            .group_by(CompanyBoard.source_slug)
        ).all()
        for source, at in last_ok:
            if at is not None:
                since_ok.add_metric([source], (now - at).total_seconds())

        latest = (
            select(SourceCheck.source_slug, func.max(SourceCheck.checked_at).label("at"))
            .group_by(SourceCheck.source_slug)
            .subquery()
        )
        checks = session.execute(
            select(SourceCheck.source_slug, SourceCheck.ok).join(
                latest,
                (SourceCheck.source_slug == latest.c.source_slug)
                & (SourceCheck.checked_at == latest.c.at),
            )
        ).all()
        for source, ok in checks:
            if source in active:
                smoke.add_metric([source], 1.0 if ok else 0.0)
        yield from (fetches, success, seconds, postings, since_ok, smoke)

    def _jobs(self, session: Session, now: datetime) -> Iterator[GaugeMetricFamily]:
        jobs = GaugeMetricFamily("erio_jobs", "Live canonical jobs by status", labels=["status"])
        live = case((Job.merged_into.is_(None), 1), else_=0)
        for status, count in session.execute(
            select(Job.status, func.sum(live)).group_by(Job.status)
        ):
            jobs.add_metric([status], int(count or 0))
        freshness = GaugeMetricFamily(
            "erio_freshness_seconds",
            "First sighting to searchable, jobs made searchable in the last day",
            labels=["quantile"],
        )
        for quantile, value in freshness_seconds(session, now).items():
            freshness.add_metric([str(quantile)], value)
        yield from (jobs, freshness)

    def _index_and_queue(self, now: datetime) -> Iterator[GaugeMetricFamily]:
        lag = GaugeMetricFamily(
            "erio_index_lag_seconds", "Time since the search indexer's last sync point"
        )
        raw = self.redis.get(WATERMARK_KEY)
        if isinstance(raw, bytes):
            lag.add_metric([], max((now - datetime.fromisoformat(raw.decode())).total_seconds(), 0))
        backlog = GaugeMetricFamily(
            "erio_queue_backlog", "Tasks waiting in a Celery queue", labels=["queue"]
        )
        backlog.add_metric([QUEUE], float(self.redis.llen(QUEUE)))
        yield from (lag, backlog)


def main() -> None:
    from erio_ingest.worker import engine, settings

    REGISTRY.register(
        PipelineCollector(engine(), Redis.from_url(settings.redis_url), lambda: datetime.now(UTC))
    )
    start_http_server(PORT)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
