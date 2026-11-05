# MetricsDown

Commands are for the local stack (`docker compose ...`). On staging and production run the same
`python -m ...` commands in the worker task, and read logs in the log service, filtered by the
fields named here.

**Fires when** Prometheus cannot scrape a target (`api` or `pipeline`) for 5 minutes.

**Impact.** The alerts for that target are blind, so trouble may be going unseen. Check the service itself first.

## Confirm

Prometheus targets page (locally http://127.0.0.1:9095/targets) shows the error.

```bash
docker compose ps api metrics
docker compose logs --since 10m metrics | tail -20
```

## Likely causes and fixes

- **The service is down**: restart it (`docker compose restart metrics`) and read its last log lines.
- **The exporter cannot reach Postgres or Redis**: its log shows the connection error; fix the dependency.
- **The API answers 404 on `/metrics`**: Prometheus is not on an internal network (`ERIO_API_INTERNAL_CIDRS`).

## Resolved when

The target is up again.

## Drill

- Rule test: `alerts.test.yml` (`pipeline` target down), in CI.
- Live, local stack, 2026-11-05: the exporter stopped. Fired after 5.5 minutes; restarting it as this page says cleared it a minute later.
