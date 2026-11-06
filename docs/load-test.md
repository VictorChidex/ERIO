# Load test

Target (spec section 10, build step 13): the public API sustains **200 requests per second** with **p95 under 300 ms** and an **error rate under 0.1%**.

**Verdict (2026-11-06): not met on the machine available, and not yet re-run on staging.** The local run found and fixed one real defect (below), after which the API passes at 100 requests per second and fails at 200. The ceiling it reached (about 110 to 120 requests per second) belongs to the shared laptop, not yet shown to belong to the code. The step 13 box stays unticked until the test is run on staging (or any machine with CPU to spare).

## Method

`loadtest/api.js` (k6) sends a fixed mix of real requests, with arrival-rate scheduling, so a slow server cannot slow the load down:

| Share | Request |
| --- | --- |
| 45% | `/v1/jobs` filtered by one of 15 countries, sometimes also by remote status, role, or salary with salary sort |
| 15% | `/v1/jobs?q=` free-text search |
| 20% | `/v1/jobs/{id}` for ids read from the API at start |
| 10% / 5% / 5% | `/v1/countries`, `/v1/platforms`, `/v1/stats` |

A 30 second warm-up at 50 requests per second, then 2 minutes at 200 requests per second. Thresholds: p95 under 300 ms and failed requests under 0.1%, both for the steady phase only. `RATE` and `DURATION` environment variables lower the rate or shorten the run to find what a machine can hold; the pass criterion is always the default.

The internal rate limit (D-15) would cap the test at 100 requests per second per caller tier, so the API ran with `ERIO_API_RATE_INTERNAL=1000000` (the same override as `loadtest/compose.yml`).

Command (k6 in Docker, on the stack's network):

```
docker run --rm --network <stack network> -e BASE_URL=http://<api>:8000 \
  -v "$PWD/loadtest:/t:ro" grafana/k6:2.2.0 run /t/api.js
```

## Environment

- One laptop: Windows 11, 8 logical CPUs, 15.8 GB memory, Docker Desktop (WSL2 VM about 6 GB).
- The data: the owner's real index, 6,186 open jobs in OpenSearch 2.18 (single shard, 512 MB heap), and a copy of the owner's Postgres database (6,547 jobs), migrated to the step 13 head. The copy lives in a scratch database (`erio13`) on the same Postgres server; the owner's database and index were only read.
- The API: the step 13 code in the production image (`docker/python.Dockerfile`), 4 uvicorn workers, run as one extra container on the existing compose network. The stack itself was not stopped, rebuilt or touched.
- **Not an idle machine.** The owner's stack kept running during every test (a crawl worker, a mock S3 server using a full core even when idle, Grafana, Prometheus and others), plus the desktop. Host CPU sat at 45 to 50% before each test. After the last runs Docker's engine stopped answering (0.3 to 0.5 GB of host memory free), taking the owner's local stack with it; it had not recovered when this was written. Results below move by a factor of two from one run to the next for that reason; read them as orders of magnitude.

## Results

All steady-phase figures; "reached" is the request rate the server actually completed.

| Run | Setup | Target | Reached | p95 | Failed | Passes |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Before the fix, API on the host (4 workers), k6 in Docker via the host | 200/s | about 105/s | 7.3 s | 0.05% | No |
| 2 | Before the fix, same | 100/s | 80/s | 643 ms | 0.68% (timeouts up to 60 s) | No |
| 3 | After the fix, same | 100/s | 100/s | 199 ms | 0.00% | Yes |
| 4 | After the fix, same | 200/s | about 111/s | 7.1 s | 0.04% | No |
| 5 | After the fix, API as a container, k6 on the same network | 200/s | about 118/s | 5.4 s | 0.00% (0 of 16,575) | No |
| 6 | Same as 5, repeated later | 200/s | about 54/s | 9.5 s | 0.00% | No |

Run 6 against run 5 shows the machine's own noise (the stack's background work and memory pressure).

## What was found

**Defect, fixed: the search client kept one connection.** Under load the API logged `Connection pool is full, discarding connection: ... pool size: 1` on almost every request. The shared OpenSearch client used urllib3's pool of 1, while the API serves up to 40 requests at once, so each concurrent request opened a new TCP connection and threw it away. At 100 requests per second that gave 0.68% failures (requests stuck up to 60 s) and p95 643 ms; with `pool_maxsize=40` (`erio_core/search/index.py`, test `test_search_client.py`) the same run had no failures and p95 199 ms.

**The remaining ceiling.** With the fix, the API still tops out near 110 to 120 requests per second here, and 8 workers did no better than 4 (about 100 per second). Evidence for where the time goes:

- The container CPU at that point: API 245% of its 400% (not saturated), OpenSearch about 160%, the rest of the host already near 100%. The host, not any one service, is out of CPU.
- OpenSearch: the list query takes 6 to 14 ms in the engine (aggregations about 1 ms of that, measured with and without them). The request cache does not apply because list queries return hits. OpenSearch reports an average query time of 25 ms under load. Its search queue never rejected a request.
- Postgres: each of the three detail-page queries costs 8 to 11 ms through Docker Desktop's port proxy from the host, and `pool_pre_ping` adds a round trip per checkout.
- Python: 21 ms of API CPU per request on average (245% over 118 requests per second), so 200 per second needs about 4.2 cores for the API alone, more than 4 workers can use.

Together this says capacity here is bounded by CPU on a shared 8-core laptop, with no single query shape or lock to blame, so no further change was made without a clean machine to measure on. Candidates, in the order to try them on staging if it still misses: turn off the duplicate uvicorn access log (`--no-access-log`; the request log already records each request), run more workers than 4 on a host with more cores, cache `/v1/jobs` answers for a few seconds (as `/v1/countries`, `/v1/platforms` and `/v1/stats` already are for 30 s), and drop `description_text` from the stored source of listing hits.

## To pass the step 13 box

Run `loadtest/api.js` unchanged on staging, with the API behind the same load balancer users will use and an idle host. Record the result here. If it fails, the CPU numbers above say where to start.
