# Build plan

ERIO is built in 14 steps. Each step ends with commits pushed to `main` and the project owner's approval before the next step begins. Tick a box only when it is true.

References: the full build spec ("ERIO — Build Spec", Claude Docs), the clickable prototype (Claude artifact "ERIO Job Index") and [backend-design.md](backend-design.md). The spec and prototype are private to the project owner until shared.

## Build order: local first

Everything is built and proven on the local `docker compose` stack before any cloud work (decision D-14). Step numbers stay as in the spec; the order below is the order of work. Until staging exists, a "done when" check that says "on staging" is met on the local stack and re-checked on staging later.

| Order | Step | Name | Status |
| --- | --- | --- | --- |
| 1 | 1 | Lock decisions and verify sources | In progress |
| 2 | 2 | Repo, local stack and CI (local parts) | Done except part e |
| 3 | 3 | Database schema and core models | Done |
| 4 | 4 | First connector and crawl pipeline | In progress |
| 5 | 5 | Failure-aware status rules | Done (live removal check pending) |
| 6 | 6 | Normalization and country resolution | Done (admin review page later) |
| 7 | 9 | Search index and API v1 | In progress |
| 8 | 10 | Website | In progress (Lighthouse, Storybook) |
| 9 | 11 | Globe and country filter | Done (60 fps to check on the reference laptop) |
| 10 | 7 | Remaining 5 connectors and company list | In progress (company list: D-07) |
| 11 | 8 | Deduplication | Done (admin merge page with the admin view) |
| 12 | 12 | AI providers and MCP server | In progress (Claude check by the owner; cloud providers wait for the vault) |
| 13 | 2e | Terraform staging and deploy on merge | On hold until local is complete |
| 14 | 13 | Observability, load and security | Not started |
| 15 | 14 | Beta and launch gate | Not started |

## Step 1 — Lock decisions and verify sources

- [x] Decisions log created (`docs/decisions.md`).
- [x] Source register created (`docs/sources.md`).
- [ ] Every open item in the decisions log has an answer or an owner and a date.
- [ ] Legal has signed off all 6 first-release sources.
- [ ] Each first-release endpoint has been called once and returns real postings.

## Step 2 — Repo, local stack and CI

Built in parts: (a) Python workspace, API and worker; (b) website skeleton; (c) `docker compose` stack; (d) CI; (e) Terraform staging skeleton, on hold until local work is complete (D-14).

- [x] Part a: Python workspace with `packages/core`, `services/api` (health endpoints) and `services/ingest` (Celery worker).
- [x] Part b: Next.js 15 website skeleton in `web/` with the prototype's design tokens, fonts, dark/light theme and a live API status.
- [x] Part c: `docker compose up --build` starts Postgres, Redis, OpenSearch, fake S3, the API, a worker and the website, with no credential anywhere.
- [x] Part d: CI on every push and pull request: credential-word check, gitleaks, Python and website checks, and a full `docker compose` run. `main` is protected: all four checks must pass.
- [ ] Part e: Terraform staging skeleton and deploy workflow (on hold, D-14).
- [ ] A fresh clone runs end to end locally with one command (`docker compose up`).
- [x] A test pull request that adds a fake credential is blocked by CI (pull request #1: gitleaks and ruff S105 failed, merge blocked).
- [ ] A merge to `main` deploys to staging automatically.

## Step 3 — Database schema and core models

Built in parts: (a) tables and migrations; (b) the 233 countries and their regions; (c) shared models `RawPosting`, `PartialJob`, `JobRecord`.

- [x] Part a: all 9 spec tables as SQLAlchemy models with an Alembic migration; a `migrate` service applies it before the API and worker start.
- [x] Migrations upgrade and downgrade cleanly on an empty database (automated test, also in CI on a real Postgres).
- [x] Part b: the 233 countries the globe draws (`web/public/geo/world.json`), with ISO codes, regions and region groups (EU, EUROPE, EMEA, AFRICA, LATAM, NORTH_AMERICA, APAC), plus the 6 first-release sources, seeded by `python -m erio_core.db.seed`. Kosovo, Somaliland and Northern Cyprus have no ISO code and use XK, XS and XN.
- [x] The 233 country names match the globe's map data exactly (automated test).
- [x] Part c: shared types in `packages/core/erio_core/schemas.py`: `RawPosting` (payload plus content hash), `PartialJob` (what a connector can parse), `JobRecord` (what the API returns).
- [x] `JobRecord` serializes to the field list in the spec (automated test, field for field and in order).

## Step 4 — First connector and crawl pipeline

Built in parts: (a) connector interface and Greenhouse adapter; (b) crawl pipeline; (c) scheduler and 20 live boards.

- [x] Part a: `Connector` interface (`board_url`, `extract`, `parse`, `discover`, `list_postings`) and the Greenhouse adapter, with contract tests on recorded fixtures in `fixtures/greenhouse/`.
- [x] Part b: crawl pipeline in `services/ingest`: polite fetcher (user agent, robots.txt, host allow-list, private-address blocking, 10 MB cap), per-host token bucket in Redis (2 requests per second), conditional requests with `ETag` (Greenhouse answers 304), payloads stored in S3 once per distinct content, a `crawl_runs` row for every attempt, boards paused for 1 hour after 5 failures, Celery task with 3 attempts and jittered backoff.
- [x] Part c: Celery beat queues due boards every minute (`beat` service); boards crawl every 15 minutes and drop to 60 after 7 quiet days; 20 starter Greenhouse boards across six continents (`erio_core/data/boards.json`) until the D-07 seed list exists. First local run: 21 boards, 3,412 real postings, no failures.
- [ ] Raw postings from 20 boards refresh every 15 minutes on staging for 48 hours.
- [x] Every fetch is recorded in `crawl_runs` with its outcome and raw payload (tests, and a live crawl of a real board).
- [ ] No host ever exceeds its configured request rate.

## Step 5 — Failure-aware status rules

Status engine in `services/ingest/erio_ingest/status.py`; failure-simulation suite in `services/ingest/tests/test_status.py`, run in CI.

- [x] The failure-simulation suite shows zero jobs closed by a failed fetch (10 failure kinds, each for two hours: 5xx, 429, 403, empty body, HTML, malformed JSON, wrong shape, empty list without a total, timeout).
- [ ] A posting removed from a live test board is closed within 45 minutes. Proven in simulation (closed 40 minutes after removal); the live check needs a board we control.
- [x] A board failing for 2 hours keeps its jobs open, then `unknown` after 72 hours, and `open` again when it recovers (simulation).

## Step 6 — Normalization and country resolution

Built in parts: (a) location and country resolution; (b) salary, role and title; (c) the normalizer that writes canonical jobs, FX rates and the review queue.

- [x] Part a: `erio_core.normalize.location` resolves country, city, state, remote status and scope from the location text, then the source's office hints, against an offline GeoNames gazetteer (`erio_core/data/gazetteer.json.gz`, CC BY 4.0). Labeled set: 305 strings (`fixtures/labeled/locations.tsv`), 220 of them real; country 99.7%, work type 100%.
- [x] Part b: salary (`normalize.salary`: ranges in any currency, separator style and period, only after a pay word), role (`normalize.roles`: ordered rules on title then departments), titles and descriptions (`normalize.text`: noise removed, HTML sanitized to an allow-list with nh3). Labeled sets: 136 salaries (salary 100%, gate 95%), 343 roles (98.8%, gate 90%).
- [x] Part c: the normalizer (`services/ingest/erio_ingest/normalizer.py`) turns every new or changed raw posting into a canonical job linked to it, after each crawl with changes and every 5 minutes; daily FX rates from the ECB with a fallback for other currencies (`fx_rates`); unresolved locations get `review_reason` and stay out of country filters. First full run on 3,413 real postings: 0 failures, 99.5% resolved, 51 countries with local listings, 1,306 salaries converted to USD.
- [x] Country accuracy ≥ 97%, salary ≥ 95%, role ≥ 90% on the labeled sets: 99.7%, 100%, 98.8%. The sets hold 305 locations, 136 salaries and 343 roles; the spec asks for 500, 300 and 300, so the location and salary sets still need growing, ideally labeled by a second person.
- [x] Every job has a country code, a list of eligible countries (remote roles limited to a region), or is marked worldwide-remote; the 0.5% that cannot be resolved wait in the review queue (`jobs.review_reason`). The admin review page comes with the admin view.
- [x] Salaries are stored in the posted currency and period; `salary_usd_annual_min` holds the USD value used only for filtering and sorting (shown by the API in step 9).

## Step 7 — Remaining 5 connectors and company list

- [x] Lever, Ashby, SmartRecruiters, Recruitee and Workable adapters in `erio_core/connectors/`, each with fixtures recorded from two real boards (`fixtures/<source>/`) and the shared contract tests in `packages/core/tests/test_connectors.py`.
- [x] The fetcher admits one-level wildcard hosts (`*.recruitee.com`, one shared rate limit), obeys robots.txt `Crawl-delay`, and reports network failures as fetch failures.
- [x] SmartRecruiters is paused: its robots.txt turns away every crawler but LinkedIn's (see `docs/sources.md`). The adapter is ready if access is granted.
- [x] Company seed list format and loader: `erio_core/data/companies.csv` (name, domain, home country), loaded by the seed. It starts with 57 employers in 17 countries across Africa, Latin America, South and Southeast Asia; the full 3,000 to 5,000 list waits on decision D-07.
- [x] Board discovery (`erio_ingest.discovery`, nightly): tries the tokens each company's name and domain suggest on every live source, records every try, and retries a miss after 30 days. A board counts only if it lists postings and, where the source names the employer, the name matches: Workable answers for empty placeholder accounts under many well-known names. First live run 2026-11-05 over the 85 companies: 393 company-and-source pairs tried, 14 boards found (among them Nubank and M-KOPA on Ashby, CRED, Meesho and Ninja Van on Lever, Groww and VTEX on Greenhouse).
- [x] Nightly live smoke test per source (`erio_ingest.smoke`): one known board per source, end to end; results in `source_checks`, failures logged as `source smoke test failed` for alerting. First live run 2026-11-05: all 5 live sources passed.
- [x] Coverage report for the targets below: `python -m erio_ingest.report`.
- [ ] All 6 sources run on staging at ≥ 98% fetch success for 3 days (5 of 6 can; SmartRecruiters is blocked by its robots.txt).
- [ ] At least 3,000 boards tracked and at least 40 countries with local listings (needs the D-07 list).
- [x] Breaking one adapter's fixture fails CI for that adapter only (checked by breaking the Ashby fixture: only Ashby tests failed).

## Step 8 — Deduplication

Every posting first becomes its own job; dedup (`erio_core/dedup.py` for the rules, `erio_ingest/dedup.py` for merging) then merges a duplicate into the job that ranks first (ATS over board, earliest `posted_at`). Each normalizer batch dedups its own jobs, and a full pass runs nightly (`python -m erio_ingest.dedup`). A merged job leaves search and its ID redirects (API 301, website 308) to the survivor, which lists every source with the primary one first. `python -m erio_ingest.dedup merges` lists the latest merges; the admin merge page comes with the admin view.

- [x] Precision ≥ 99% and recall ≥ 90% on the labeled pairs: 100% and 93.0% on 600 pairs from real crawled postings (`fixtures/labeled/dedup_pairs.json.gz`, built by `scripts/build_dedup_pairs.py`), with the rules tuned as in D-16. The spec's rules as written scored 57.5% and 68.7%.
- [x] A job posted on 2 sources shows once in search, listing both: TrueLayer's 4 jobs on Greenhouse and Ashby, on the local stack and in tests.
- [x] Dedup of a full crawl cycle finishes in under 5 minutes: 5 seconds for all 5,260 local jobs (143 seconds the first time, when every job is fingerprinted once). To re-check at 3,000 boards.

On the local data the full pass merged 72 jobs, mostly one employer posting the same job several times (Coinbase lists one Manila support role 22 times). One known false merge: Gympass's Berlin and Munich sales roles, because the normalizer finds no city in "Germany (Berlin- Hybrid)".

## Step 9 — Search index and API v1

Built in parts: (a) OpenSearch index and indexer; (b) `/v1/jobs` and `/v1/jobs/{id}`; (c) `/v1/countries`, `/v1/platforms`, `/v1/stats`; (d) tokens and rate limits.

- [x] Part a: one document per open or unknown job with a resolved place, behind the `jobs` alias; `filter_countries` (own country plus countries a remote role accepts) drives both the country filter and its facet. The indexer follows `jobs.updated_at` every 20 seconds (60-second overlap) and rebuilds into a new index nightly, swapping the alias with no downtime.
- [x] Part b: `GET /v1/jobs` with `q`, `country`, `include_worldwide`, `remote_status`, `role`, `salary_min_usd`, `platform`, `posted_after`, `status`, `sort`, `cursor`, `per_page`; facets count every filter except their own; cursor pagination with `search_after`; one error shape with a request ID. `GET /v1/jobs/{id}` returns the full description.
- [x] Part c: `GET /v1/countries` (233 countries, filterable and local counts, top city pins), `GET /v1/platforms` (status, boards, jobs, 24-hour fetch success), `GET /v1/stats` (totals, refresh lag).
- [x] Part d: Bearer tokens (32 random bytes, only the SHA-256 stored, revocable, `python -m erio_api.tokens`), tiers and sliding-window rate limits in Redis with `X-RateLimit-*` headers and 429 + `Retry-After` (D-15). The API recreates a missing search index instead of failing.
- [x] `country=NG` returns Nigerian jobs plus remote roles open to Nigeria; `include_worldwide=false` removes worldwide ones (API tests on Postgres and OpenSearch).
- [x] Facet counts per country match a direct database count (API tests).
- [ ] p95 < 300 ms at 200 requests per second (load test in step 13). Over-limit returns 429 with rate-limit headers: done (tests).

## Step 10 — Website

- [x] The prototype's design system (tokens, classes, both themes) ported as `web/app/globals.css`; pages: Home, Search, job detail with `JobPosting` data, Coverage, API reference (generated from the OpenAPI spec) and country landing pages (`/countries/[code]`), all server-rendered from the live API with no hard-coded numbers and no "78 sources" claim.
- [x] Search filters live in the URL (`country`, `ww`, `type`, `role`, `salary`, `sort`), work without JavaScript, and apply instantly with it; searchable 233-country list ordered as the spec asks; chips, Popular countries, worldwide toggle with "Open to you", empty states, Load more.
- [x] Playwright tests (desktop and 360 px) check pages and numbers against the API; CI loads demo jobs from the recorded fixtures (`python -m erio_ingest.demo`) and runs them on the production build.
- [ ] Storybook component library (spec deliverable) — not built yet.
- [x] Every page uses the prototype's layout and styling in both themes (the globe arrives in step 11; the AI search bar with step 12).
- [x] A copied search URL reproduces the same results (browser test).
- [ ] Lighthouse ≥ 90 (performance, accessibility) on mobile: not measured yet. No horizontal scroll at 360 px: done (browser tests).

## Step 11 — Globe and country filter

Globe in `web/components/Globe.tsx` (d3-geo on a canvas, loaded after the page is idle); the draw rules in `web/lib/globe-geometry.ts` are shared with the rotation-sweep test.

- [x] Clicking a country on the Home globe opens Search filtered to it; on the Search globe it toggles the country (browser tests).
- [x] Rotation sweep finds no full-sphere flash: every country at every rotation in 10-degree steps (`web/e2e/globe-sweep.unit.ts`). Each part of a country is drawn on its own, and a part the horizon clipper inverts is skipped for that frame.
- [ ] 60 fps on the reference laptop: to check by hand with `GLOBE_PERF=1 npx playwright test globe --workers=1`. Headless CI browsers draw in software (10 to 35 fps here), so frame rate is not a CI gate.
- [x] Everything the globe does also works by keyboard: the globe picks a country, and the searchable country list and header country menu do the same by keyboard. Reduced motion turns off spin and arcs (browser test).

## Step 12 — AI providers and MCP server

Built in parts: (a) the AI gateway with 4 adapters; (b) a local model and the normalizer fallback; (c) the MCP server and tool definitions.

- Part a: `erio_core/ai`. Adapters for OpenAI, Anthropic, Gemini and any OpenAI-compatible server call each provider's HTTPS API with httpx (D-17). Routing per task lives in `routing.json`. The gateway falls back on any failure, retries invalid JSON once, opens a circuit per provider, enforces daily dollar and token caps, never calls an unpriced model, caches answers by task and input, and logs every call to `ai_calls`. Contract tests cover each adapter's request, token header, response and failure kinds.
- Part b: Ollama runs two small open models locally (`docker compose --profile ai up`), with no token. Every 5 minutes the fallback asks about jobs the rules left open: role "other", the location review queue, and pay mentioned but no salary found. A model serves a task only while its latest labeled-set score reaches the task's gate (role 90%, location 97%, salary 95%). A salary must come with the sentence it was read from, found in the job text, containing both amounts and a pay word. `python -m erio_ingest.ai_eval` scores every usable model and the rules on the same rows, nightly too.
- Part c: `services/mcp`, a read-only MCP server at http://127.0.0.1:8100/mcp with `search_jobs`, `get_job`, `list_countries` and `list_platforms`, calling `/v1` like any client and passing on the caller's token. OpenAI and Gemini tool definitions are generated from the same tools and shown on the API page.

- [x] Switching a task's provider needs only a config change, and the labeled-set scores are reported for both: tests switch routing between providers; `ai_eval` scored both local models (results below).
- [x] Disabling any one provider mid-run causes no failed jobs: tests switch a provider off mid-run and fail every provider; jobs keep their rule results and are tried again later.
- [ ] Claude and at least one other MCP client can search ERIO jobs by country: the official MCP Python client and a plain JSON-RPC client both searched Nigeria and Kenya on the local stack, and CI does the same search. Claude is for the owner to check (`claude mcp add --transport http erio http://127.0.0.1:8100/mcp`).
- [ ] The OpenAI, Anthropic and Gemini adapters pass live contract tests: they pass recorded-shape tests now; live calls wait for the credential vault (D-17) and prices and a budget (D-18).

Labeled-set scores on the local stack (60 rows per task, spread evenly; 2026-11-05):

| Task | Rules | qwen2.5 1.5B | llama3.2 1B | Gate |
| --- | --- | --- | --- | --- |
| Role | 98.3% | 66.7% | 41.7% | 90% |
| Location | 100% | 86.7% | 5.0% | 97% |
| Salary | 100% | 83.3% | 15.0% | 95% |

Neither local model reaches any gate, so locally the fallback calls no model and every job keeps its rules result. The salary scores are from before the quote check was added. Before the gate existed, the fallback wrote invented salaries (copied from the prompt, or company funding read as pay) into 43 local jobs. Those jobs were normalized again from their stored postings, and the gate and the quote check now stop this. Larger cloud models are expected to pass, which can be checked once D-17 and D-18 are settled.

## Step 13 — Observability, load and security

- [ ] Each alert has fired once in a staging drill and its runbook was followed.
- [ ] Load test passes: p95 < 300 ms, error rate < 0.1% at 200 requests per second.
- [ ] Credential-word check, gitleaks and image scan are clean.

## Step 14 — Beta and launch gate

- [ ] Every MVP acceptance criterion in the spec is met.
- [ ] 7 days of production with zero jobs closed by a failed fetch.
- [ ] The project owner signs off the launch.
