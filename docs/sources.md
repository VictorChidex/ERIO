# Source register

One row per job source. A source goes live only when all three checks are done: the endpoint has been called and returns real postings, its rate limits are known, and legal has reviewed its terms.

The endpoints below are the publicly documented, employer-published job-board feeds as we understand them. Each is verified from a machine with normal internet access before its connector is built; the table records when.

## First release (6 sources)

| Source | Public endpoint | Documentation | Auth | Endpoint verified | Rate limits known | Legal review |
| --- | --- | --- | --- | --- | --- | --- |
| Greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true` | [Job Board API](https://developers.greenhouse.io/job-board.html) | None for reads | Yes (2026-11-05; 20 boards return real postings; robots.txt allows `/v1/`) | Partly: no rate-limit headers or published limit; sends `ETag`. ERIO stays at 2 requests per second | Not started |
| Lever | `GET https://api.lever.co/v0/postings/{company}?mode=json` | [Postings API](https://github.com/lever/postings-api) | None for reads | No | No | Not started |
| Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` | [Public job posting API](https://developers.ashbyhq.com/docs/public-job-posting-api) | None for reads | No | No | Not started |
| SmartRecruiters | `GET https://api.smartrecruiters.com/v1/companies/{company_id}/postings` | [Posting API](https://developers.smartrecruiters.com/docs/posting-api) | None for reads | No | No | Not started |
| Recruitee | `GET https://{company}.recruitee.com/api/offers/` | To confirm | None for reads | No | No | Not started |
| Workable | Public careers feed per account (exact endpoint to confirm) | To confirm | To confirm | No | No | Not started |

## How to verify a source

1. Pick two real companies known to use the source.
2. Call the endpoint for each and save the raw response under `fixtures/<source>/` (added in step 4).
3. Record the observed limits (response headers, documented limits) in this table.
4. Link the terms of use and record the legal reviewer and date.

## Not allowed

Job boards whose terms forbid automated collection (LinkedIn, Indeed, Glassdoor, ZipRecruiter and similar) are never crawled. They can enter only through licensed feeds or partner programs in a later phase (decision D-05).

## Reference data

Data ERIO reads to normalize jobs, not job postings. Each is fetched from a fixed address, never scraped.

| Data | Source | Licence and terms | Used for |
| --- | --- | --- | --- |
| Places | [GeoNames](https://www.geonames.org) `cities15000` and `admin1CodesASCII`, built into `erio_core/data/gazetteer.json.gz` by `scripts/build_gazetteer.py` | CC BY 4.0: credit GeoNames | City, state and country resolution |
| Country codes and regions | [mledoze/countries](https://github.com/mledoze/countries), pinned commit, built into `erio_core/data/countries.json` by `scripts/build_countries.py` | ODbL 1.0 | ISO codes, regions, region groups |
| Map | [world-atlas](https://github.com/topojson/world-atlas) (Natural Earth 50m), simplified, in `web/public/geo/world.json` | Natural Earth is public domain; world-atlas is ISC | The globe and the 233-country list |
| FX rates | [ECB euro reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html), daily | Free reuse with the ECB as source | USD value of salaries in ~30 currencies |
| FX rates (fallback) | [ExchangeRate-API open access](https://www.exchangerate-api.com/docs/free) (`open.er-api.com`), daily | Free; attribution required ("Rates By Exchange Rate API" with a link) where converted values are shown | USD value for currencies the ECB does not publish (NGN, KES, GHS, ...) |
