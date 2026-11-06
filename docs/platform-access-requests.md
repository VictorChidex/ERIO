# Access requests for blocked platforms

Five platforms of the coverage brief turn crawlers away, so ERIO does not read them
(decision D-19: a platform whose robots.txt or terms refuse crawlers is never worked
around). The route to covering them is the platform's permission or an official feed.
Send one request per platform, then record the answer here. Until a platform says yes
in writing, `docs/coverage.md` keeps it Blocked.

Replace `<contact>` with the crawler mailbox once D-06 is decided.

| Platform | What blocks it | What to ask for |
| --- | --- | --- |
| SmartRecruiters | robots.txt turns away every crawler except one | Permission to read the public postings API for customer boards, or a partner feed |
| Paycor | robots.txt on recruitingbypaycor.com disallows everything | Permission to read public postings, or a feed of public postings |
| Dover | The job data endpoints are disallowed; only job URLs are allowed | Permission to read the data endpoints for public postings, or a feed |
| Talenetic | Hosted boards disallow everything and require sign-in | Permission to read public postings of boards that are public, or a feed |
| Artha | Job pages answer with a bot-protection challenge | Allow-listing of ERIO's crawler, or a feed of public postings |

## Message to send

> Subject: Request to index your customers' public job postings (ERIO job search)
>
> Hello,
>
> ERIO is a job-search service that links candidates to employers' own application pages.
> We would like to include the public job postings that employers publish through
> **<platform>**, and we can only do that with your permission: <what blocks it, from the
> table>.
>
> What we ask: <what to ask for, from the table>.
>
> How we crawl, if you allow it:
> - We identify ourselves with a fixed user agent and a contact address (`<contact>`).
> - We obey robots.txt, including the rules you set for us, and any Crawl-delay.
> - We read at most one request per second per host, and only public postings.
> - We store the posting and always send candidates to the employer's own apply page.
> - We close a posting when it disappears, and we remove any posting on request.
> - We never log in, solve challenges or read anything that is not public.
>
> If you offer a partner feed, an API agreement or different terms, we are glad to use
> them instead. Please reply to `<contact>`.
>
> Thank you,
> <name>, ERIO

## Answers

| Platform | Sent | Answer |
| --- | --- | --- |
| SmartRecruiters | | |
| Paycor | | |
| Dover | | |
| Talenetic | | |
| Artha | | |
