# SourceFetchSuccessLow

Commands are for the local stack (`docker compose ...`). On staging and production run the same
`python -m ...` commands in the worker task, and read logs in the log service, filtered by the
fields named here.

**Fires when** a source's fetch success over the last hour is below 90% for 5 minutes.

**Impact.** Jobs from that source go stale. None close, but after 72 hours without a good fetch they turn `unknown` and leave default search results.

## Confirm

1. Grafana "Sources and pipeline": "Fetch success" and "Fetches by outcome" for the source.
2. Which outcome dominates, and on which boards:

```bash
docker compose exec postgres psql -U erio -d erio -c "select b.board_token, r.outcome, r.http_status, count(*), max(left(r.error, 80)) from crawl_runs r join company_boards b on b.id = r.board_id where b.source_slug = 'SOURCE' and r.started_at > now() - interval '1 hour' group by 1, 2, 3 order by 4 desc limit 20"
```

## Likely causes and fixes

| Outcome | Cause | Action |
| --- | --- | --- |
| `rate_limited` (429) on many boards | We exceed the source's limit | Lower `ERIO_CRAWL_RATE_PER_HOST`, or raise board cadence; the per-host limiter shares one bucket across workers |
| `http_error` 403 everywhere | Blocked, or robots.txt changed | Check robots.txt by hand; if the source has opted us out, pause it (`update sources set status = 'paused'`) within 24 hours, as the source policy requires |
| `http_error` 404 on a few boards | Company moved ATS or closed its board | Remove those boards, let discovery find the new one |
| `parse_error` | The source changed its response format | Record a fresh fixture, update the connector, and run its contract tests |
| `timeout` | Source slow or down | Check the source's status page; usually clears by itself |

## Resolved when

The ratio is back above 90% for an hour. Boards with 5 failures in a row pause for an hour on their own and then retry.

## Drill

- Rule test: `alerts.test.yml` (Lever at 85%), in CI.
