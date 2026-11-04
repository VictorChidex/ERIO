# Build plan

ERIO is built in 14 steps. Each step ends with commits pushed to `main` and the project owner's approval before the next step begins. Tick a box only when it is true.

References: the full build spec ("ERIO — Build Spec", Claude Docs) and the clickable prototype (Claude artifact "ERIO Job Index"). Both are private to the project owner until shared.

| Step | Name | Weeks | Status |
| --- | --- | --- | --- |
| 1 | Lock decisions and verify sources | 1 | In progress |
| 2 | Repo, local stack and CI | 1–2 | In progress |
| 3 | Database schema and core models | 2 | Not started |
| 4 | First connector and crawl pipeline | 2–3 | Not started |
| 5 | Failure-aware status rules | 3 | Not started |
| 6 | Normalization and country resolution | 3–5 | Not started |
| 7 | Remaining 5 connectors and company list | 4–6 | Not started |
| 8 | Deduplication | 5–6 | Not started |
| 9 | Search index and API v1 | 5–7 | Not started |
| 10 | Website | 5–8 | Not started |
| 11 | Globe and country filter | 6–8 | Not started |
| 12 | AI providers and MCP server | 6–8 | Not started |
| 13 | Observability, load and security | 8–9 | Not started |
| 14 | Beta and launch gate | 8–10 | Not started |

## Step 1 — Lock decisions and verify sources

- [x] Decisions log created (`docs/decisions.md`).
- [x] Source register created (`docs/sources.md`).
- [ ] Every open item in the decisions log has an answer or an owner and a date.
- [ ] Legal has signed off all 6 first-release sources.
- [ ] Each first-release endpoint has been called once and returns real postings.

## Step 2 — Repo, local stack and CI

Built in parts: (a) Python workspace, API and worker; (b) website skeleton; (c) `docker compose` stack; (d) CI; (e) Terraform staging skeleton.

- [x] Part a: Python workspace with `packages/core`, `services/api` (health endpoints) and `services/ingest` (Celery worker).
- [x] Part b: Next.js 15 website skeleton in `web/` with the prototype's design tokens, fonts, dark/light theme and a live API status.
- [x] Part c: `docker compose up --build` starts Postgres, Redis, OpenSearch, fake S3, the API, a worker and the website, with no credential anywhere.
- [ ] A fresh clone runs end to end locally with one command (`docker compose up`).
- [ ] A test pull request that adds a fake credential is blocked by CI.
- [ ] A merge to `main` deploys to staging automatically.

## Step 3 — Database schema and core models

- [ ] Migrations upgrade and downgrade cleanly on an empty database.
- [ ] The 233 country names match the globe's map data exactly (automated test).
- [ ] `JobRecord` serializes to the field list in the spec.

## Step 4 — First connector and crawl pipeline

- [ ] Raw postings from 20 boards refresh every 15 minutes on staging for 48 hours.
- [ ] Every fetch is recorded in `crawl_runs` with its outcome and raw payload.
- [ ] No host ever exceeds its configured request rate.

## Step 5 — Failure-aware status rules

- [ ] The failure-simulation suite shows zero jobs closed by a failed fetch.
- [ ] A posting removed from a live test board is closed within 45 minutes.
- [ ] A board failing for 2 hours keeps its jobs open, then `unknown` after 72 hours.

## Step 6 — Normalization and country resolution

- [ ] Country accuracy ≥ 97%, salary ≥ 95%, role ≥ 90% on the labeled sets.
- [ ] Every job has a country code or is marked worldwide-remote.
- [ ] Salaries display in the posted currency; filtering uses the USD value.

## Step 7 — Remaining 5 connectors and company list

- [ ] All 6 sources run on staging at ≥ 98% fetch success for 3 days.
- [ ] At least 3,000 boards tracked and at least 40 countries with local listings.
- [ ] Breaking one adapter's fixture fails CI for that adapter only.

## Step 8 — Deduplication

- [ ] Precision ≥ 99% and recall ≥ 90% on the labeled pairs.
- [ ] A job posted on 2 sources shows once in search, listing both.
- [ ] Dedup of a full crawl cycle finishes in under 5 minutes.

## Step 9 — Search index and API v1

- [ ] `country=NG` returns Nigerian jobs plus remote roles open to Nigeria; `include_worldwide=false` removes worldwide ones.
- [ ] Facet counts per country match a direct database count.
- [ ] p95 < 300 ms at 200 requests per second; over-limit returns 429 with rate-limit headers.

## Step 10 — Website

- [ ] Every page matches the prototype in both themes.
- [ ] A copied search URL reproduces the same results.
- [ ] Lighthouse ≥ 90 (performance, accessibility) on mobile; no horizontal scroll at 360 px.

## Step 11 — Globe and country filter

- [ ] Clicking a country on the Home globe opens Search filtered to it; on the Search globe it toggles the country.
- [ ] Rotation sweep finds no full-sphere flash; 60 fps on the reference laptop.
- [ ] Everything the globe does also works by keyboard; reduced motion turns off spin and arcs.

## Step 12 — AI providers and MCP server

- [ ] Switching a task's provider needs only a config change.
- [ ] Disabling any one provider mid-run causes no failed jobs.
- [ ] Claude and at least one other MCP client can search ERIO jobs by country.

## Step 13 — Observability, load and security

- [ ] Each alert has fired once in a staging drill and its runbook was followed.
- [ ] Load test passes: p95 < 300 ms, error rate < 0.1% at 200 requests per second.
- [ ] Credential-word check, gitleaks and image scan are clean.

## Step 14 — Beta and launch gate

- [ ] Every MVP acceptance criterion in the spec is met.
- [ ] 7 days of production with zero jobs closed by a failed fetch.
- [ ] The project owner signs off the launch.
