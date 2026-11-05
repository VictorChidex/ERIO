# Backend design

How ERIO's backend turns ATS job feeds into the data every page of the website needs. The full detail of each part is in the build spec (sections 3–7); this page is the map. Everything below runs locally in `docker compose` first; cloud deployment comes last (decision D-14).

## What the website needs

Each page of the prototype maps to one API call. The website uses the same public `/v1` API as outside developers.

| Page | What it shows | API call |
| --- | --- | --- |
| Home | Live job count, number of sources, refresh lag | `GET /v1/stats` |
| Home | Globe: job counts per country, city pins, arcs | `GET /v1/countries` |
| Home | "Recently indexed" ticker | `GET /v1/jobs?sort=recent` |
| Search | Job cards: title, company, city and country, work type, salary, source, posted time, "Verified open" | `GET /v1/jobs` |
| Search | Filter counts per country, work type and role | `meta.facets` in the same response |
| Search | "Open to you" badge on worldwide-remote roles | `remote_scope` and `eligible_country_codes` on each job |
| Job detail | Full description, apply link, "also posted on" | `GET /v1/jobs/{canonical_id}` |
| AI search | Plain-English request turned into filter chips | `POST /v1/ai/parse-query` (returns filters, never jobs) |
| Coverage | Each source's status, board count, last success | `GET /v1/platforms` |
| API | Reference documentation | Generated from `/v1/openapi.json` |
| Sign in, Get API key | API tokens | Admin-only in the first release |

`GET /v1/jobs` takes `q`, `country` (comma-separated ISO codes), `include_worldwide` (default true), `remote_status`, `role`, `salary_min_usd`, `platform`, `posted_after`, `status` (default `open`), `sort` (`recent`, `salary`, `relevance`), `cursor` and `per_page` (default 25, max 100). Filter state on the site lives in the URL, so every search can be shared.

## Data flow

```
 ATS feeds: Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee, Workable
      │  scheduler (Celery beat) queues each board every 15 minutes
      │  workers fetch through per-host rate limits held in Redis
      ▼
 crawl_runs + raw payload in S3  ──►  raw_postings      what each source said
      ▼
 normalizer: country, remote scope, salary in USD, role
      ▼
 dedup in 3 passes  ──►  jobs + job_sources            what ERIO believes
      ▼
 indexer  ──►  OpenSearch  ◄──  API: /v1/jobs (search and facets)
 Postgres ◄────────────────────  API: /v1/jobs/{id}, /v1/countries,
                                      /v1/platforms, /v1/stats
                                         ▲
                          website (Next.js) calls the same /v1 API
```

## Components

| Component | Code | Job |
| --- | --- | --- |
| Shared models | `packages/core` | `RawPosting`, `PartialJob`, `JobRecord`, settings, connector interface |
| Connectors | `packages/core` (connectors) | One adapter per source: `discover`, `list_postings`, `parse`. Adapters never write to the database |
| Scheduler and workers | `services/ingest` | Queue boards, fetch politely, record every fetch in `crawl_runs`, store raw payloads |
| Status engine | `services/ingest` | Applies the five failure-aware status rules (below) |
| Normalizer | `services/ingest` | Location and country, remote scope, salary and USD value, role category; unresolved jobs go to a review queue |
| Dedup | `services/ingest` | Exact ID, exact key, then SimHash near-duplicates within the same company and country |
| Indexer | `services/ingest` | Updates OpenSearch within 60 seconds of a change; nightly rebuild with no downtime |
| API | `services/api` | The `/v1` endpoints above, cursor pagination, rate limits, one error shape |

## Where data lives

- **Postgres** is the source of truth: `sources`, `companies`, `company_boards`, `crawl_runs`, `raw_postings`, `jobs`, `job_sources`, `countries` (233 entries matching the globe) and `api_tokens`, as defined in spec section 4.
- **OpenSearch** answers searches and facet counts. It can be rebuilt from Postgres at any time.
- **Redis** holds the task queue and per-host rate limits.
- **S3** (S3Mock locally, decision D-13) keeps raw payloads for 30 days so any crawl can be replayed.

## Rules that protect trust

1. A fetch is successful only with HTTP 200 and a payload that parses.
2. Failed fetches never change a job's status.
3. A posting missing from 2 successful fetches at least 30 minutes apart is closed.
4. A job not verified for 72 hours becomes `unknown` and leaves default results.
5. A closed job that reappears is reopened with the same `canonical_id`.

No count on the website is hard-coded: every number comes from the API.

## Later-phase features in the prototype

AI search and user sign-in appear in the prototype but belong to later phases of the spec. The website port keeps their place in the layout; they are connected when the AI gateway (step 12) and accounts (phase 2) exist.
