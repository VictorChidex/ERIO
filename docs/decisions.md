# Decisions log

Every project-level decision lives here. "Proposed" means the build team suggests it and the project owner has not yet agreed; "Agreed" means it is settled. Change a decision by adding a new row that replaces the old one, never by editing history.

Owner: Chidex (project owner) unless stated otherwise.

| ID | Decision | Status | Notes |
| --- | --- | --- | --- |
| D-01 | Stack: Python 3.12 (FastAPI, Celery, SQLAlchemy) for ingest and API; Next.js 15 with TypeScript for the website | Agreed | Chosen at planning |
| D-02 | Data stores: PostgreSQL 16 (source of truth), OpenSearch 2.x (search), Redis 7 (queue, rate limits), S3 (raw payloads, 30 days) | Agreed | From the spec |
| D-03 | Cloud provider for staging and production: AWS | Proposed | GCP is the alternative; affects Terraform from step 2 |
| D-04 | First release scope: 6 ATS sources (Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee, Workable) | Agreed | Job boards only later, through licensed feeds |
| D-05 | No scraping of job boards whose terms forbid it (LinkedIn, Indeed, Glassdoor, ZipRecruiter and similar) | Agreed | Non-negotiable |
| D-06 | Crawler identity: user agent `ERIO-Indexer/1.0 (+https://<domain>/bot)` with a contact address | Proposed | Needs the product domain and a contact mailbox |
| D-07 | Company seed list: 3,000–5,000 employers across at least 40 countries, weighted toward Africa, Latin America, South and Southeast Asia | Proposed | Needs an owner for building the list |
| D-08 | Security rules: no credentials in the repo, in environment variables or in container images; production credentials only in the cloud credential vault; `.env.example` holds placeholders only; the credential-word check must pass before any merge | Agreed | Original project rule, kept as written in the spec |
| D-09 | How the credential-word check treats the one module that reads from the cloud credential vault | Proposed | Proposal: that module and the AI provider adapters live under `infra/` and `packages/core/ai/providers/`, and the check runs on everything else plus a leak scanner (gitleaks) on the whole repo |
| D-10 | AI providers: one internal gateway with adapters for OpenAI, Anthropic and Google Gemini, plus one OpenAI-compatible adapter | Agreed | Spec section 13 |
| D-11 | Data retention: closed jobs kept 12 months, raw payloads 30 days | Proposed | |
| D-12 | Default branch `main`; every step lands as reviewed commits on `main` | Agreed | Set at build start |
| D-13 | Local fake S3 is Adobe S3Mock (`adobe/s3mock`), not MinIO | Proposed | MinIO no longer publishes free container images (its Docker Hub repository is gone and quay.io needs a login). S3Mock is Apache-2.0 and accepts requests without any credential, so the local stack stays credential-free. Staging and production use real S3 |
| D-14 | Build and prove everything on the local `docker compose` stack first; Terraform, staging and cloud deploys come after the local build is complete | Agreed | Owner's call. Search and API v1 (step 9) move before the website (steps 10–11); D-03 can wait until then. See `docs/build-plan.md` |
| D-15 | API access tiers: requests from networks in `ERIO_API_INTERNAL_CIDRS` (locally, the compose networks) need no token; others use a Bearer token (free 100/min, pro 2,000/min) or are anonymous (30/min per address). Limits use the connecting address, never a forwarded header | Proposed | Keeps the local stack credential-free (D-08): the website calls the API without a token. In production the website fetches a token from the cloud credential vault (Phase 4), and the internal list is left empty |
| D-16 | Dedup rules tuned on the 600 labeled pairs: near-duplicates need Hamming distance ≤ 6 (spec: ≤ 3), places that do not differ (city, state or region, and the countries a remote role accepts), and the same title once place words are removed; the exact key keeps the apply URL query values that name a job and drops only tracking ones (spec: host and path) | Proposed | With the spec's rules as written: precision 57.5%, recall 68.7%. Template descriptions merged different roles, offices and sales territories (Datadog lists one remote role per US state), and careers pages such as `stripe.com/jobs/search?gh_jid=…` share one path. With these rules: precision 100%, recall 93.0%; the first false merge appears at distance 12. Merges are kept when a posting changes later; `python -m erio_ingest.dedup merges` lists them |
| D-17 | AI providers are called over their plain HTTPS APIs with httpx, not their SDKs; the access token goes only in a request header, handed over by a credential source (the cloud vault in production). Locally the gateway uses a self-hosted model through Ollama, which needs no token. The OpenAI, Anthropic and Gemini adapters are contract-tested against their documented requests and responses and go live once the vault exists | Agreed | Owner's call (2026-11-05). Keeps D-08 as written and the credential-word check repo-wide, so D-09 is no longer needed for AI |
| D-18 | AI launch defaults: tasks route to local models first, then Claude, OpenAI and Gemini as fallbacks; each task capped at $5 and 2 million tokens a day. Cloud models carry no price yet, and the gateway never calls an unpriced model, so they stay off until prices and a budget are set | Proposed | The spec's open questions: which providers are the defaults at launch, and the monthly AI budget. Model IDs and prices live in `erio_core/ai/routing.json` |
| D-19 | Platform coverage (the acquisition brief's 58 ATS and 20 job-board platforms): a platform counts as covered only when live runs on two or more of its boards fetched, parsed and normalized every job, and `docs/coverage.md` is generated from those runs, never edited by hand; a platform whose robots.txt or terms turn crawlers away is reported Blocked and never worked around; a platform is built only when an ordinary anonymous visitor session reaches its jobs (an anonymous token or CSRF cookie the site issues to everyone: CSOD, BrassRing, Dayforce; the public search host a career page itself calls: talentReef); the owner decided on 2026-11-05 to cover Paycom and talentReef, but Paycom's robots.txt disallows its job-list endpoint, so it stays Blocked | Proposed | The first coverage commit marked 73 platforms live with no live run behind them; the checklist now computes its status from `docs/coverage/results.json`. Blocked so far: SmartRecruiters, Paycor, Dover, Talenetic, Paycom, Artha; permission requests are drafted in `docs/platform-access-requests.md` |
| D-20 | Role categories cover every kind of work, not only tech: the spec's 8 categories stay as they are, and `other` is split into healthcare, education, hospitality, retail, logistics, trades and security (15 in all), so nurses, drivers, cooks, teachers and the like can be found by role; a title naming an engineer or developer stays in a tech category; `python -m erio_ingest.reclassify` moves stored `other` jobs when the rules change | Proposed | The new platforms (Taleo, Paylocity, Workday, Dayforce, talentReef and others) carry mostly non-tech jobs: 42% of the recorded sample landed in `other` under the 8 categories, 20% after the split, and accuracy on the labeled titles is 99% (gate: 90%) |

## Open items for the project owner

- [ ] D-03: confirm AWS, or choose GCP (not needed until local work is complete, D-14).
- [ ] D-06: product domain name and the crawler contact mailbox.
- [ ] D-07: who builds the company seed list, and which countries matter most at launch. The format and loader are ready (`erio_core/data/companies.csv`: name, domain, home country), with 57 starter employers; board discovery finds their boards on its own.
- [ ] D-09: agree the scope of the credential-word check.
- [ ] D-11: confirm retention periods.
- [ ] D-13: agree S3Mock as the local fake S3.
- [ ] D-15: agree the API access tiers and the internal-network rule.
- [ ] D-16: agree the tuned dedup rules.
- [ ] D-18: launch AI providers, model IDs and prices, and the monthly AI budget.
- [ ] D-19: agree the platform coverage rules, and send the permission requests for the blocked platforms.
- [ ] D-20: agree the wider role categories.
- [ ] Legal review of the 6 MVP sources (see `docs/sources.md`).
