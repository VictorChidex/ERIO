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

## How this repo is built

- Work happens one step at a time, in the order of `docs/build-plan.md`.
- Each step ends with one or more commits and a push to `main`, and the project owner approves it before the next step starts.
- No credential of any kind is ever committed. See the security rules in `docs/decisions.md` (D-08).
