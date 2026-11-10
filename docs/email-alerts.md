# CV upload and email job alerts

A person opens **Workspace, Profile & alerts**, uploads a CV, and ERIO emails them the new jobs that fit it.
Still no account and no password: the workspace key stays in the browser.

## What happens

1. **Upload** (`POST /v1/workspace/profile/resume`, raw bytes plus `X-Filename`): PDF, Word `.docx` or text, up to 2 MB.
   The file is read in memory (`erio_api/cvfile.py`: PDF page cap, XML parsed with `defusedxml`, size caps before
   unpacking) and **dropped**. The skills found (fixed word list, no AI model) are kept in `workspace_profiles`.
2. **Profile** (`PUT /v1/workspace/profile`): skills (removable), up to five job titles, countries, remote only,
   minimum match, and the look of the workspace (colour, spacing, start tab, cards shown).
3. **Jobs for me** (`GET /v1/workspace/profile/jobs`): open jobs indexed in the last 30 days, ranked by how much of
   each job's requirements the skills cover. Identical title, employer and place count once.
4. **Email** (`PUT /v1/workspace/mail`): needs a profile. A confirmation message is sent; nothing else is sent until
   its link is opened (the page asks for a button press, so mail scanners that open links cannot confirm).
   Limits: three confirmation emails an hour per workspace and per address.
5. **Digest** (Celery task `erio.email_digests`, hourly on the pipeline queue): each confirmed, unpaused address
   that is due (23 hours for daily, a week less an hour for weekly) gets the top 10 new matches it has not been sent.
   Five provider failures in a row pause the address.
6. **Stop**: every email links to `/alerts/<manage token>` to pause, switch daily/weekly or delete the address.
   That token can do nothing else. Deleting the workspace deletes the address and the profile.

## Turning real email on (Resend)

Credentials never go in settings or the image (decision D-08). Put the Resend API key in a file, mount it into the
`api` and `worker-pipeline` containers, and set:

| Variable | Meaning |
| --- | --- |
| `ERIO_RESEND_API_KEY_FILE` | Path of the mounted file holding the API key |
| `ERIO_MAIL_FROM` | Sender, for example `ERIO <alerts@your-domain>`; needs a domain verified in Resend (the default `onboarding@resend.dev` only delivers to the account owner) |
| `ERIO_SITE_URL` | Public address of the website; the links in the emails use it |

With no key file, messages are **logged instead of sent** (`erio.mail` logger), so the whole flow can be tried
locally: ask for alerts, read the confirmation link in the API log, confirm, then run the task once:

```bash
docker compose exec worker-pipeline python -c "from erio_ingest.worker import email_digests_task; print(email_digests_task())"
```

## Still to decide

- A sending domain (D-06) so mail does not come from `resend.dev`.
- Legal review of the alert emails (consent record, unsubscribe wording, retention) before the public launch.
- Whether to add a one-click `List-Unsubscribe-Post` endpoint: today the header links to the manage page.
