# Runbooks

One page per alert in `infra/observability/alerts.yml`. Each alert's `runbook_url` points here.

| Alert | Severity | Page |
| --- | --- | --- |
| SourceFetchSuccessLow | page | [source-fetch-success-low.md](source-fetch-success-low.md) |
| SourceStoppedDelivering | page | [source-stopped-delivering.md](source-stopped-delivering.md) |
| SourceSmokeTestFailed | ticket | [source-smoke-test-failed.md](source-smoke-test-failed.md) |
| IndexLagHigh | page | [index-lag-high.md](index-lag-high.md) |
| QueueBacklogHigh | page | [queue-backlog-high.md](queue-backlog-high.md) |
| ApiErrorRateHigh | page | [api-error-rate-high.md](api-error-rate-high.md) |
| MetricsDown | page | [metrics-down.md](metrics-down.md) |

**Where to look**

- Dashboards: Grafana "ERIO · Sources and pipeline" and "ERIO · API" (locally http://127.0.0.1:3001 with `docker compose --profile obs up`).
- Alerts: Alertmanager (locally http://127.0.0.1:9093).
- Logs: one JSON object per line. Filter by `request_id` (API), `crawl_run_id`, `board_id` or `source` (crawler), `task` (worker). Each line has a `trace_id` to open the trace in Jaeger (locally http://127.0.0.1:16686).
- Raw data: `crawl_runs` records every fetch with its outcome, HTTP status and error.

**A failed fetch never closes a job** (spec section 5). Fetch alerts are about freshness, not about losing jobs: jobs stay open and turn `unknown` only after 72 hours without a successful fetch.

**Drills.** `promtool test rules infra/observability/alerts.test.yml` (in CI) fires every alert on synthetic data. Live drills are recorded at the end of each page.
