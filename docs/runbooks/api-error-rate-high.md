# ApiErrorRateHigh

Commands are for the local stack (`docker compose ...`). On staging and production run the same
`python -m ...` commands in the worker task, and read logs in the log service, filtered by the
fields named here.

**Fires when** more than 1% of API requests answer 5xx over 5 minutes, for 1 minute.

**Impact.** Clients and the website get errors. Every error body carries a `request_id`.

## Confirm

1. Grafana "ERIO · API": "5xx share" and "Responses by status".
2. Which routes, and what failed:

```bash
docker compose logs --since 10m api | grep '"status": 5'  | tail -20
```

Take a `request_id` from a client report or the log, and its `trace_id` to Jaeger to see the failing step.

## Likely causes and fixes

- **503 from `/v1/health/ready`, or many 503s**: a dependency is down. `curl -s http://127.0.0.1:8000/v1/health/ready` names it (Postgres, Redis, OpenSearch).
- **500 on one route after a release**: roll back the release; the trace shows the exception.
- **OpenSearch errors**: see the cluster health in [index-lag-high.md](index-lag-high.md).
- **Database connections exhausted**: many `QueuePool limit` errors. Scale API tasks down or raise the pool size.

## Resolved when

The 5xx share is back under 1%.

## Drill

- Rule tests: `alerts.test.yml` (2% fires, 0.1% stays quiet), in CI.
- Live, local stack, 2026-11-05: OpenSearch stopped under steady traffic. Fired after 2 minutes; following this page (readiness named OpenSearch; started it) cleared it 6 minutes later, once the 5-minute window passed.
