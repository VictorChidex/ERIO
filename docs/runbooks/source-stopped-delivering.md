# SourceStoppedDelivering

Commands are for the local stack (`docker compose ...`). On staging and production run the same
`python -m ...` commands in the worker task, and read logs in the log service, filtered by the
fields named here.

**Fires when** no board of an active source has fetched successfully for over an hour, for 5 minutes. This is the spec's "a source stops delivering" alert.

**Impact.** Every job from that source is going stale; after 72 hours they turn `unknown`.

## Confirm

1. Grafana: "Time since last successful fetch".
2. Is the worker crawling at all, or only this source failing?

```bash
docker compose ps worker beat
docker compose logs --since 30m worker | grep '"crawl finished"' | grep '"source": "SOURCE"' | tail
```

## Likely causes and fixes

- **Beat stopped**: no `erio.schedule_due_boards` lines in the worker logs. Restart it: `docker compose restart beat`.
- **Workers stuck or the queue backed up**: see [queue-backlog-high.md](queue-backlog-high.md).
- **Every board paused**: `select count(*) from company_boards where source_slug = 'SOURCE' and paused_until > now()`. Find out why with the queries in [source-fetch-success-low.md](source-fetch-success-low.md).
- **The source is down or blocks us**: run its live smoke test, `docker compose exec worker python -c "from erio_ingest.worker import smoke_test_sources_task as t; print(t())"`.

## Resolved when

A successful fetch brings the time below an hour.

## Drill

- Rule test: `alerts.test.yml` (Ashby silent past an hour), in CI.
