# Reference study: jobindex.space

A mature job index built on the same idea as ERIO, read on 2026-11-09 from its public pages
(home, sources, coverage, pulse, how-it-works, API and MCP pages, robots.txt, sitemap, one
landing page, one job page, one company page). Everything below is what those pages show or say;
where this document infers, it says so. Nothing here copies the product's text, markup or code.

## How it indexes

| Stage | What it does | Evidence |
| --- | --- | --- |
| Find boards | Reads employers' boards on applicant tracking systems, **public job services** (government and open feeds), and **boards found in public web archives** | "How it works": "boards found in public web archives" |
| Read on a schedule | Every board is read again; large sources "just now", small ones every few hours to days | Sources page: "read just now" to "read 5d ago" per source |
| Clean | Places to countries, remote and hybrid, salary range and period, a field (healthcare, trades, ...) | How it works; job page |
| Deduplicate | Same role on several boards becomes one job that remembers every listing | "SOURCES (1)" table on a job; "3 boards -> 1 job" |
| Index | A dedicated search engine kept in step with the database | How it works |
| Close | A role that disappears from its source is closed on the next read | How it works; "ingested" count above the live count on the sources page |

Scale at the time: about 4.16 million open jobs, 204,000 companies, 233 sources, 160 ATS platforms.
ERIO today: about 30,000 jobs, 172 boards, 78 platforms tracked, 68 verified.

## What it does differently from ERIO

1. **Discovery is the engine.** It tracks 204,000 companies (Greenhouse alone: 8,159 boards).
   ERIO's board list came from a seed list and name guessing. Discovery from the Internet
   Archive's index of archived addresses is the one lever that moves ERIO from hundreds to
   tens of thousands of boards. *Built (see below).*
2. **Public job services as sources.** Government and open feeds (Bundesagentur fuer Arbeit,
   EURES, Arbeitnow, Arbetsfoermedlingen, MyCareersFuture, NAV, remote-job boards) fill whole
   countries. ERIO has none. *Not built: each needs its own research and terms check.*
3. **Coverage is an operating state, not a one-off proof.** A platform is "covered" while at
   least 3 boards were read successfully in the last 2 days; each row shows boards ok/total,
   open jobs, 7-day runs ok/failed, and the share of jobs with description, place, posted
   date and salary. *Built (live columns on ERIO's coverage page and `GET /v1/coverage`).*
4. **Provenance on every job.** A table of platform, listing, first seen, last checked and
   status per source, plus a history. *Being built (job page, agent branch `seo-pages`).*
5. **Indexable by design.** About 1,200 curated landing pages (`/jobs/in/{country}`,
   `/jobs/in/{country}/{role|city}`, `/jobs/role/{title}`), a sharded sitemap (pages plus one
   file per ~50,000 companies), `noindex, follow` on pages with too few jobs, filtered
   query URLs disallowed in robots.txt (only pagination allowed), AI-training crawlers
   blocked, and a pointer to the API and MCP server for data users. *Being built.*
6. **Analytics from its own data.** A market pulse (roles added vs removed per day over 30
   days, freshness, pay quartiles per currency, never converted) and a page per company.
   *Being built (agent branch `insights-pages`).*
7. **An API and MCP server as products.** Search, a change feed (only what was added, closed
   or changed since the last cursor), bulk download; MCP tools for jobs, companies, filter
   values, market and salary statistics, and platform coverage. *MCP tools being extended.*
8. **No `JobPosting` structured data.** Job pages carry Organization, WebSite and
   BreadcrumbList only, since the user applies on the employer's page. ERIO follows this.

## Where ERIO decided differently, on purpose

- The reference lists platforms ERIO has marked **blocked**: SmartRecruiters, Paycom, Paycor,
  Dayforce, Dover, Artha, talentReef (and Taleo/BrassRing at small scale). ERIO's rule
  (decision D-19) is that a platform whose robots.txt or protection turns crawlers away is
  not read until it agrees. How the reference reads them is not visible from its pages, so
  ERIO does not assume it is lawful. See decision D-24 for the question this raises.
- The reference discloses it did not bypass a restriction on two platforms
  (CareerSiteCloud, Talenetic). ERIO's policy matches.
- Common Crawl's public index would be a second archive source, but its robots.txt closes it
  to crawlers, so ERIO does not use it.

## What was built from this study

- `erio_ingest/archive_discovery.py`: reads the Internet Archive's CDX index page by page for
  17 address shapes across 14 platforms, turns archived addresses into candidate board tokens,
  probes each with its connector, registers only boards that list postings, remembers
  rejections, resumes where it stopped, and runs every 6 hours. **Tested against recorded
  answers only: the archive was offline when this was written, so it has not run live.**
- `GET /v1/coverage` live fields and the coverage page columns (live now, boards ok/total,
  open jobs, 7-day runs, data completeness, last success).

- `GET /v1/changes` (a cursor-paged feed of added, changed, closed, reopened and merged jobs)
  and `GET /v1/export/jobs` (every open job as gzipped NDJSON, resumable with `after=`).
- Nine public job services as connectors, a real employer per job on multi-employer boards, a
  history per job, pay sanity checks, `/salary`, `/paths`, `/guides`, `/new`, search feeds and a
  no-account workspace (saved jobs, tracker, saved searches, CV match).
- Archive discovery now covers 23 address shapes and shares its probe budget evenly between
  platforms.

## Not yet done

- Run the archive discovery live once the Internet Archive answers, and watch the crawl
  load that thousands of new boards bring.
- The platforms the reference lists as covered but ERIO keeps blocked (decision D-24), and
  Himalayas (its terms forbid passing jobs on to other feeds).
