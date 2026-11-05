# SourceSmokeTestFailed

Commands are for the local stack (`docker compose ...`). On staging and production run the same
`python -m ...` commands in the worker task, and read logs in the log service, filtered by the
fields named here.

**Fires when** the nightly live smoke test for a source failed. The test fetches one known board per source (`erio_ingest.smoke`). Severity is ticket: look the next working day.

**Impact.** None yet, but the source may have changed its API or blocked us, so crawls are likely to fail next.

## Confirm

```bash
docker compose exec postgres psql -U erio -d erio -c "select source_slug, board_token, checked_at, ok, left(error, 120) from source_checks order by checked_at desc limit 12"
```

Run it again now:

```bash
docker compose exec worker python -c "from erio_ingest.worker import smoke_test_sources_task as t; print(t())"
```

## Likely causes and fixes

- **The canary board itself closed**: the company moved ATS. Pick another busy board for that source in `erio_ingest/smoke.py`.
- **Format change**: the error says parse. Record a new fixture and update the connector.
- **Blocked or robots.txt change**: follow the source policy in [source-fetch-success-low.md](source-fetch-success-low.md).

## Resolved when

The next smoke test passes (`erio_source_smoke_ok` back to 1).

## Drill

- Rule test: `alerts.test.yml` (Workable failing), in CI.
