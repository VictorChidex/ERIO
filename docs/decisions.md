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

## Open items for the project owner

- [ ] D-03: confirm AWS, or choose GCP.
- [ ] D-06: product domain name and the crawler contact mailbox.
- [ ] D-07: who builds the company seed list, and which countries matter most at launch.
- [ ] D-09: agree the scope of the credential-word check.
- [ ] D-11: confirm retention periods.
- [ ] Legal review of the 6 MVP sources (see `docs/sources.md`).
