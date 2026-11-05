# QueueBacklogHigh

Commands are for the local stack (`docker compose ...`). On staging and production run the same
`python -m ...` commands in the worker task, and read logs in the log service, filtered by the
fields named here.

**Fires when** more than 10,000 tasks wait in the crawl queue for 5 minutes.

**Impact.** Boards are crawled late; data goes stale, and index lag and fetch alerts may follow.

## Confirm

```bash
docker compose exec redis redis-cli llen crawl
docker compose exec worker celery -A erio_ingest.worker inspect active
```

## Likely causes and fixes

- **Workers down or stuck**: no active tasks. `docker compose restart worker`.
- **Too few workers for the board count**: add workers (`docker compose up -d --scale worker=3`; on AWS, raise the task count).
- **A slow source holds every worker**: look for one source with long fetch times in Grafana; lower its rate or pause it.
- **The scheduler queued the same boards twice**: should not happen (boards are queued once per due time); if the backlog is mostly repeats, purge the queue (`docker compose exec worker celery -A erio_ingest.worker purge -Q crawl -f`) and let beat queue due boards again within a minute.

## Resolved when

The backlog drains below 10,000.

## Drill

- Rule test: `alerts.test.yml` (12,000 tasks waiting), in CI.
