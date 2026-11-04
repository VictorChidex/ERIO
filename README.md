# ERIO

ERIO is a real-time job index. It collects job postings from applicant tracking systems (ATS), cleans them into one standard record, removes duplicates, and serves them through a search website and a REST API. Anyone can filter jobs by any country in the world.

**Status:** Step 1 of 14 (decisions and source checks). Nothing is deployed yet.

## Documents

| Document | What it holds |
| --- | --- |
| [docs/build-plan.md](docs/build-plan.md) | The 14 build steps, in order, with "done when" checks |
| [docs/decisions.md](docs/decisions.md) | Every project decision, who owns it, and its status |
| [docs/sources.md](docs/sources.md) | The job sources ERIO reads, their endpoints, terms and review status |

The full technical spec and the clickable prototype live outside this repo and are linked from `docs/build-plan.md`.

## Repo layout

| Path | What lives there |
| --- | --- |
| `packages/core` | Shared Python code (`erio_core`): settings now, models and connectors later |
| `services/api` | Public REST API (`erio_api`, FastAPI) |
| `services/ingest` | Crawl scheduler and workers (`erio_ingest`, Celery) |
| `web/` | Website (Next.js 15, TypeScript strict), ported from the prototype |
| `docs/` | Decisions, sources and the build plan |

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

Settings come from `ERIO_*` environment variables (see `packages/core/erio_core/settings.py`). They hold service addresses only, never credentials.

## How this repo is built

- Work happens one step at a time, in the order of `docs/build-plan.md`.
- Each step ends with one or more commits and a push to `main`, and the project owner approves it before the next step starts.
- No credential of any kind is ever committed. See the security rules in `docs/decisions.md` (D-08).
