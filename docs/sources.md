# Source register

One row per job source. A source goes live only when all three checks are done: the endpoint has been called and returns real postings, its rate limits are known, and legal has reviewed its terms.

The endpoints below are the publicly documented, employer-published job-board feeds as we understand them. None has been verified yet: the build environment's network does not currently allow these hosts. Verification happens from a machine with normal internet access, or once the hosts are allowed.

## First release (6 sources)

| Source | Public endpoint | Documentation | Auth | Endpoint verified | Rate limits known | Legal review |
| --- | --- | --- | --- | --- | --- | --- |
| Greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true` | [Job Board API](https://developers.greenhouse.io/job-board.html) | None for reads | No | No | Not started |
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
