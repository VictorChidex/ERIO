# IndexLagHigh

Commands are for the local stack (`docker compose ...`). On staging and production run the same
`python -m ...` commands in the worker task, and read logs in the log service, filtered by the
fields named here.

**Fires when** the search index's last sync point is more than 15 minutes old, for 2 minutes. The indexer syncs every 20 seconds, so normal lag is under a minute.

**Impact.** Search shows old data: new jobs are missing, closed jobs still show. The API and site keep working.

## Confirm

1. Grafana: "Index lag".
2. Is the indexer task running, and what does it say?

```bash
docker compose logs --since 10m worker | grep erio.index_changed | tail -5
docker compose exec redis redis-cli get erio:indexer:watermark
```

## Likely causes and fixes

- **Beat stopped**: no `erio.index_changed` tasks. `docker compose restart beat`.
- **OpenSearch down or red**: `curl -s http://127.0.0.1:9200/_cluster/health`. Restart it, then run a full rebuild:
  `docker compose exec worker python -c "from erio_ingest.worker import rebuild_index_task as t; print(t())"`.
- **A long open database transaction** holds the sync point back (the indexer waits for any transaction that started earlier). Find it:
  `select pid, now() - xact_start, state, left(query, 80) from pg_stat_activity where datname = 'erio' and xact_start is not null order by xact_start limit 5`.
  Let it finish, or end it with `select pg_terminate_backend(PID)` if it is stuck.
- **Each sync takes too long**: an index task run takes over 20 seconds (see "succeeded in" in its log line); look at the trace in Jaeger.

## Resolved when

Lag is back under a minute.

## Drill

- Rule test: `alerts.test.yml` (lag jumping to 1,000 seconds), in CI.
- Live, local stack, 2026-11-05: beat stopped and the sync point set 20 minutes back. Fired after 2.5 minutes; restarting beat as this page says cleared it 3.5 minutes later.
