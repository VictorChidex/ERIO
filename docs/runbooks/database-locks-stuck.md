# Database locks stuck

Not an alert yet: the signs are writers that stop (jobs and the index stop growing, crawl runs
never finish) while the API still answers searches. It happened once on the local stack, when the
S3 mock (the local raw payload store at the time) was killed under memory pressure and the normalizer waited on it inside a transaction. The local stack now keeps raw payloads as files, so this is a cloud S3 failure mode locally only with `--profile s3`.

Commands are for the local stack (`docker compose ...`).

**Impact.** New postings stop becoming jobs; everything queued behind the stuck transaction waits.
Searches keep working on the last indexed data.

## Confirm

```bash
docker compose exec postgres psql -U erio -d erio -c "select pid, state, wait_event_type, now()-xact_start as age, left(query,80) from pg_stat_activity where datname='erio' and state<>'idle' order by xact_start"
```

A session `idle in transaction` for minutes, with others waiting on `Lock`, is the signature.

## Likely causes and fixes

- **Object storage down or slow** (S3, or the fake S3 under `--profile s3`): check it, start it, then restart the workers (`docker compose restart worker worker-live beat`), which drops their connections and releases the locks.
- **A worker crashed mid-batch**: the same restart.
- **Memory pressure** (`s3` or `worker` exit code 137): free memory or lower the worker count (`-c` in `docker-compose.yml`); the crawl worker runs four processes.

Never end database sessions by hand: restarting the worker rolls back its batch cleanly, and the
postings stay pending for the next run.

## Built-in limits

Postgres ends a session left in an open transaction for 5 minutes and one waiting on a lock for 60
seconds (`ERIO_DB_IDLE_IN_TRANSACTION_S`, `ERIO_DB_LOCK_TIMEOUT_S`), and the S3 client gives up
after 5 s to connect and 30 s to read, with three retries. The normalizer reads raw payloads and the
crawler stores them with no transaction open, so object storage can no longer hold row locks. A
stall like the one above now ends on its own within minutes instead of hours.

## Resolved when

No session is `idle in transaction` for more than a few minutes, and `jobs` counts grow again.
