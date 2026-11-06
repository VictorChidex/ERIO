# ERIO

ERIO is a real-time job index. It collects job postings from applicant tracking systems (ATS), cleans them into one standard record, removes duplicates, and serves them through a search website and a REST API. Anyone can filter jobs by any country in the world.

**Status:** Step 2 (local stack and CI) done; Step 3 (database) next. Everything runs locally; nothing is deployed yet.

## Documents

| Document | What it holds |
| --- | --- |
| [docs/build-plan.md](docs/build-plan.md) | The 14 build steps, the local-first order of work, and "done when" checks |
| [docs/backend-design.md](docs/backend-design.md) | What each page needs from the API, and how data flows from ATS feeds to search |
| [docs/decisions.md](docs/decisions.md) | Every project decision, who owns it, and its status |
| [docs/sources.md](docs/sources.md) | The job sources ERIO reads, their endpoints, terms and review status |

The full technical spec and the clickable prototype live outside this repo and are linked from `docs/build-plan.md`.

## Repo layout

| Path | What lives there |
| --- | --- |
| `packages/core` | Shared Python code (`erio_core`): settings, database models, connectors, normalizer, dedup rules and the AI gateway (`erio_core.ai`) |
| `services/api` | Public REST API (`erio_api`, FastAPI) |
| `services/ingest` | Crawl scheduler and workers (`erio_ingest`, Celery) |
| `services/mcp` | Read-only MCP server (`erio_mcp`): AI assistants search ERIO jobs as a tool |
| `web/` | Website (Next.js 15, TypeScript strict), ported from the prototype |
| `docs/` | Decisions, sources and the build plan |

## Run everything locally

Needs [Docker Desktop](https://www.docker.com/products/docker-desktop/) (on Windows, with the WSL 2 backend) and about 4 GB of free memory.

```bash
docker compose up --build
```

| Service | Address | Notes |
| --- | --- | --- |
| Website | http://localhost:3000 | Home, Search (`/search?country=NG`), job pages, Coverage, API reference, country pages (`/countries/ng`) |
| API | http://localhost:8000/v1/jobs | `/v1/jobs`, `/v1/jobs/{id}`, `/v1/countries`, `/v1/platforms`, `/v1/stats`; interactive docs at `/v1/docs` |
| Worker | — | Celery, crawls boards from the `crawl` queue |
| Beat | — | Queues every due board once a minute |
| Postgres 16 | localhost:5432 | Database and user `erio`; trusts local connections. Tables are created by the one-off `migrate` service |
| Redis 7 | localhost:6379 | Queue and rate limits |
| OpenSearch 2 | http://localhost:9200 | Search; security plugin off locally |
| Raw payloads | volume `raw-data` | Plain files under `/data/raw` (decision D-13); `docker compose --profile s3 up` adds a fake S3 on http://localhost:9090 |
| MCP server | http://127.0.0.1:8100/mcp | Tools `search_jobs`, `get_job`, `list_countries`, `list_platforms`; OpenAI and Gemini definitions at `/tools/openai.json` and `/tools/gemini.json` |

Nothing in the stack needs a credential, and every port listens on 127.0.0.1 only. Stop with `docker compose down`; add `-v` to also delete the local data.

**Local AI (optional).** The AI gateway fills in roles, locations and salaries the rules could not read, using a small open model through Ollama, which needs no token (decision D-17). Add the `ai` profile to run it; the first start downloads the Ollama image (about 8 GB) and two models (about 2.3 GB). Without it, AI fallbacks are skipped and jobs keep their rule results.

```bash
docker compose --profile ai up --build
```

Score the models against the labeled sets (`--limit` samples rows evenly):

```bash
docker compose exec worker python -m erio_ingest.ai_eval --limit 60
```

**Claude.** Add the MCP server to Claude Code, then ask, for example, for remote engineering jobs open to Nigeria:

```bash
claude mcp add --transport http erio http://127.0.0.1:8100/mcp
```

## Python services

The Python code is one [uv](https://docs.astral.sh/uv/) workspace on Python 3.12.

```bash
uv sync --all-packages              # install everything into .venv
uv run pytest                       # tests
uv run ruff check . && uv run mypy  # lint and type-check
uv run uvicorn erio_api.main:app --reload   # API on http://localhost:8000/v1/health
```

## Website

```bash
cd web
npm ci                # install exact versions from package-lock.json
npm run dev           # http://localhost:3000 (expects the API on localhost:8000)
npm run lint && npm run typecheck && npm run build
```

The site reads the API address from `ERIO_API_URL` (default `http://localhost:8000`).

### API tokens

Locally the website and your own machine reach the API without a token (decision D-15). To try the token tiers:

```bash
docker compose exec api python -m erio_api.tokens create --email you@example.com
curl -H "Authorization: Bearer <token>" http://localhost:8000/v1/stats
```

The token is printed once and only its hash is stored. `list` and `revoke --id N` manage them.

### Database migrations

The schema lives in `packages/core/erio_core/db/models.py`; Alembic migrations are in `packages/core/erio_core/db/migrations/`. `docker compose up` applies them automatically. To work with them by hand:

```bash
uv run alembic -c packages/core/alembic.ini upgrade head      # apply
uv run alembic -c packages/core/alembic.ini revision --autogenerate -m "describe change"
```

A test fails if the models and migrations ever differ, so every schema change needs a migration.

Settings come from `ERIO_*` environment variables (see `packages/core/erio_core/settings.py`). They hold service addresses only, never credentials.

## Checks (CI)

GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs on every push and pull request:

| Job | What it runs |
| --- | --- |
| Credential scan | `scripts/check-credential-words.sh` (decision D-08) and gitleaks over the full history |
| Python | ruff, ruff format, mypy (strict), pytest |
| Website | ESLint, TypeScript, `next build` |
| Local stack | `docker compose up --build`, checks the API, worker and website answer, then runs the frontend tests |

A fresh stack has no jobs until beat crawls the boards. To load a small known set offline (the recorded fixtures, through the real pipeline; only on an empty database):

```bash
docker compose run --rm -v "$PWD/fixtures:/app/fixtures:ro" worker python -m erio_ingest.demo /app/fixtures
```

Frontend tests use [Playwright](https://playwright.dev) against the running stack, on desktop and at 360 px. They check every number against the API, so they pass on demo data and on real crawls:

```bash
docker compose up --build -d --wait
cd web
npx playwright install chromium   # first time only
npm run test:e2e
```

Run the credential check yourself before every commit:

```bash
bash scripts/check-credential-words.sh
```

## How this repo is built

- Work happens one step at a time, in the order of `docs/build-plan.md`.
- Each step ends with one or more commits and a push to `main`, and the project owner approves it before the next step starts.
- No credential of any kind is ever committed. See the security rules in `docs/decisions.md` (D-08).
