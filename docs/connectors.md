# Connector notes

How each of the 78 platforms in the brief publishes its jobs, as found by reading each
platform's live career sites on 2026-11-05 (request by request, honouring robots.txt),
and what stops a connector. Coverage status lives in [coverage.md](coverage.md); this is
the reference for building or fixing a connector. Nothing here uses a login, a private
key or a bot-protection workaround, and nothing may be added that does.

Board token: the identifier a connector is given for one employer's or job board's site
(a subdomain, a slug, or the board's `https://` address for sites on their own domain).

## Applicant tracking systems

### ADP

- **Read via:** the platform's own JSON or XML interface. The Workforce Now career center calls a public JSON API with no login. The list gives title, location, post date, pay range and work level. A detail request adds the HTML description.
- **List:** `GET https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions?cid={cid}&lang=en_US&locale=en_US&$top=20&$skip=0`
- **Paging:** OData $top/$skip; meta.totalNumber gives the total
- **Detail:** `https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions/{itemID}?cid={cid}&lang=en_US&locale=en_US`
- **Board token:** WFN: cid, a UUID taken from the career-center URL https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid={cid}&ccId=...; apply URL = that page plus &jobId={itemID}. RM / MyJobs: a site slug, as in https://myjobs.adp.com/{slug}
- **Own-domain sites:** Employers link to the workforcenow.adp.com or myjobs.adp.com URL, often inside an iframe on their own careers page. You can tell them by those hosts and by a cid= UUID in the link. Older RM sites use recruiting.adp.com/srccar/public/RTI.home?c=...
- **robots.txt:** None of the three hosts serves a robots.txt. workforcenow.adp.com/robots.txt and my.adp.com/robots.txt return 302 to the online.adp.com login page. myjobs.adp.com/robots.txt returns the SPA HTML shell. Nothing disallows these paths.
- **Blockers:** WFN: none found. MyJobs (RM): the list endpoint https://my.adp.com/myadp_prefix/mycareer/public/staffing/v1/job-requisitions/apply-custom-filters ($top/$skip) needs headers myjobstoken and orgoid. The token is a short-lived public session token found in the career-site config response. I did not send it (see notes), so the MyJobs list is unverified. MyJobs detail is .../job-requisitions/search-meta/{reqId}.
- **Notes:** Remote/onsite is not a separate field; infer it from location names such as 'Telecommuting'. The first tested cid (978f4299-...) returned 0 jobs, which shows that tenants with no openings return an empty list rather than an error. Building a MyJobs connector depends on whether reading the public session token from the config is acceptable; that is for the owner to decide.
- **Live boards seen:** Science Systems and Applications, Inc (SSAI) (6 jobs), WFN tenant cid=2de708e1-c847-43b1-bf0d-0bad30aca014 (name not in the payload) (1 jobs), Sempra (MyJobs config only; list not fetched) (None jobs), Guitar Center (MyJobs config only; list not fetched) (None jobs)

### ApplicantPro

- **Read via:** the platform's own JSON or XML interface. The career site's Vue component calls a public JSON jobs endpoint. Detail pages carry full schema.org JobPosting JSON-LD.
- **List:** `GET https://{subdomain}.applicantpro.com/core/jobs/{domainId}?getParams={"isInternal":0}`
- **Paging:** None observed; one response returns every job (data.jobCount equals jobs length)
- **Detail:** `https://{subdomain}.applicantpro.com/jobs/{id} (HTML with JobPosting JSON-LD: description, datePosted, employmentType, baseSalary)`
- **Board token:** The subdomain plus a numeric domainId. Read domainId from the HTML of https://{subdomain}.applicantpro.com/jobs/ ('domainId : 3465' in the componentData script). Without the getParams query parameter the endpoint returns a PHP error.
- **Own-domain sites:** Hosted on {subdomain}.applicantpro.com. Disabled or unknown tenants redirect to /notset.php?{sub}&root=4. https://feeds.applicantpro.com/site_map_index.xml lists a job_site_map.xml for every active tenant, which helps discover boards.
- **robots.txt:** User-agent: * / Disallow: /admin/ /stats/ /internaljobs/ /internaljobsbyorganization/ /internaljobsbyorganizationmap/ /internaljobsearch/ / Sitemap: https://feeds.applicantpro.com/site_map_index.xml. /jobs/ and /core/jobs/ are allowed.
- **Notes:** Send isInternal:0 so internal-only postings stay out (the /internaljobs paths are disallowed in robots.txt anyway). endDateRef holds the closing date.
- **Live boards seen:** NorthWestern Energy (19 jobs), AgTexas Farm Credit (6 jobs), Village of Palatine IL (live board, no openings) (0 jobs)

### Ashby

- First-release connector; endpoint and limits are in [sources.md](sources.md).

### Avature

- **Read via:** the job pages' HTML (no feed or structured data). Each tenant has an RSS feed, but it returns only the 20 newest jobs with title, link and date. The full set comes from the tenant sitemap plus detail-page HTML, which has no JSON-LD.
- **List:** `GET https://{tenant}.avature.net/{portal}/sitemap.xml (all JobDetail URLs); RSS: https://{host}/{locale?}/{portal}/SearchJobs/feed/`
- **Paging:** The RSS feed is fixed at 20 items: jobRecordsPerPage and jobOffset are ignored. The HTML search /SearchJobs/?jobOffset={n}&jobRecordsPerPage=12 pages in steps of 12. The sitemap has every job in one file.
- **Detail:** `https://{host}/{portal}/JobDetail/{slug}/{id} (HTML; per-tenant template, fields in article__content__view__field blocks)`
- **Board token:** Host plus portal path, e.g. bloomberg.avature.net + 'careers', or jobs.ea.com + 'en_US/careers'. The portal name varies (careers, jobs, SearchJobsTechnology...). The job ID is the last path segment of JobDetail.
- **Own-domain sites:** Common, e.g. jobs.ea.com, careers.ibm.com, apply.deloitte.com, jobs.totalenergies.com, talent.ecb.europa.eu. You can tell them by the /{portal}/SearchJobs and /{portal}/JobDetail/{slug}/{id} paths, the /SearchJobs/feed/ RSS and robots.txt 'Disallow: /careers/*qtvc='.
- **robots.txt:** bloomberg.avature.net: 'User-agent: * / Allow: /$ / Allow: /careers / Disallow: /careers/*qtvc= / Sitemap: https://bloomberg.avature.net/careers/sitemap_index.xml'. delta.avature.net and jobs.ea.com: 'Allow: /careers / Disallow: /careers/*qtvc= / Allow: /*/careers'. The feed, sitemap and JobDetail paths are allowed.
- **Notes:** The detail-page layout differs by tenant. A generic parser can take the title and main content area, but structured fields need per-tenant label matching. Use RSS for cheap incremental polling and the sitemap for full reconciliation. Bloomberg and EA detail pages had no JobPosting JSON-LD.
- **Live boards seen:** Bloomberg (332 jobs), Bloomberg (RSS) (20 jobs), Delta Air Lines (RSS) (20 jobs), Electronic Arts, custom domain (RSS) (20 jobs)

### BambooHR

- **Read via:** the platform's own JSON or XML interface. The public careers page calls JSON endpoints with no auth: one for the list and one for detail, which has the full HTML description.
- **List:** `GET https://{company}.bamboohr.com/careers/list`
- **Paging:** None; meta.totalCount equals result length
- **Detail:** `https://{company}.bamboohr.com/careers/{id}/detail (JSON: result.jobOpening.description, datePosted, compensation, employmentStatusLabel, locationType, jobOpeningShareUrl)`
- **Board token:** Company subdomain, e.g. 'instabug'. An unknown subdomain gets a 302 to https://www.bamboohr.com.
- **Own-domain sites:** Hosted only on {company}.bamboohr.com. Employers embed it via the BambooHR widget script (embed code pointing at {company}.bamboohr.com/careers). You can tell it by that host or a /careers/list XHR.
- **robots.txt:** instabug.bamboohr.com/robots.txt: 'User-Agent: * / Disallow:' (everything allowed)
- **Notes:** The locationType meanings were inferred from samples ('1' = a remote role with no city; '2' = a role with a city that is not onsite). Confirm them against more boards before relying on them.
- **Live boards seen:** LXT (48 jobs), Instabug (Luciq) (2 jobs), VertiGIS (live, no openings) (0 jobs)

### BrassRing

- **Read via:** the platform's own JSON or XML interface. The TalentGateway UI posts to a JSON search endpoint that needs no login. Each call needs a session cookie, an anti-forgery token and an encrypted session value, all taken from the public search page.
- **List:** `POST https://sjobs.brassring.com/TgNewUI/Search/Ajax/MatchedJobs`
- **Request body:** `{"PartnerId":"{partnerid}","SiteId":"{siteid}","Keyword":"","Location":"","LocationCustomSolrFields":"Location","FacetFilterFields":null,"TurnOffHttps":false,"Latitude":0,"Longitude":0,"PowerSearchOptions":{"PowerSearchOption":[]},"encryptedsessionvalue":"{hidden input CookieValue}"}  with headers RFT: {hidden __RequestVerificationToken}, Content-Type: application/json, plus cookies from GET https://sjobs.brassring.com/TGnewUI/Search/Home/Home?partnerid={partnerid}&siteid={siteid}`
- **Paging:** 50 per page; JobsCount is the total. Later pages come from POST /TgNewUI/Search/Ajax/ProcessSortAndShowMoreJobs with pageNumber (not exercised here).
- **Detail:** `https://sjobs.brassring.com/TGnewUI/Search/home/HomeWithPreLoad?partnerid={partnerid}&siteid={siteid}&PageType=JobDetails&jobid={reqid} (hidden input preLoadJSON holds Jobdetails JSON)`
- **Board token:** partnerid + siteid (numbers from the career-site URL)
- **Own-domain sites:** Employers link to sjobs.brassring.com/TGnewUI/... from their own sites. Old links use sjobs.brassring.com/TGWebHost/jobdetails.aspx?partnerid=..&siteid=..&jobid=.. . Many old partner/site pairs are dead: they return 500 or 'This site is temporarily unavailable'.
- **robots.txt:** https://sjobs.brassring.com/robots.txt returns 404, so no rules apply
- **Blockers:** No login, CAPTCHA or bot wall. The search needs the session, RFT and CookieValue steps above; this is the page's own anti-forgery flow, not bot protection. List fields are tenant-defined 'Questions' (formtextNN), so location and type mapping differ by employer.
- **Notes:** Only one board returned non-empty results. The empty RIT and Lockheed results may be real, or a body difference for those sites. Check the body with one more large tenant before building. The question names that carry location are listed in the page's JobFieldsToDisplay.
- **Live boards seen:** Walgreens (22598 jobs), Rochester Institute of Technology (site loads; search returned 0) (0 jobs), Lockheed Martin legacy site (loads; search returned 0) (0 jobs)

### Breezy HR

- **Read via:** the platform's own JSON or XML interface. Every Breezy portal serves its open positions as JSON at /json; ?verbose=true adds the HTML description. Detail pages also carry JobPosting JSON-LD.
- **List:** `GET https://{company}.breezy.hr/json?verbose=true`
- **Paging:** None; one top-level JSON array of all published positions
- **Detail:** `https://{company}.breezy.hr/p/{friendly_id} (HTML with JobPosting JSON-LD incl. datePosted, employmentType, baseSalary)`
- **Board token:** Company subdomain (company.friendly_id), e.g. 'elite-amenity-management'. Unknown subdomains return 404.
- **Own-domain sites:** Some employers point a custom careers domain at the Breezy portal. You can tell it by /p/{12-hex-id}-{slug} job URLs and a /json path that returns the same array.
- **robots.txt:** {company}.breezy.hr/robots.txt: 'User-Agent: * / Disallow: /css /fonts /stylesheets /javascripts' and 'User-Agent: AhrefsBot / Disallow: /'. /json and /p/ are allowed.
- **Notes:** The salary is a display string such as '$0.05 – $0.06 / hour' and needs parsing.
- **Live boards seen:** German American Chambers of Commerce (39 jobs), Elite Amenity Management (42 jobs)

### CareerPlug

- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). There is no public JSON (/jobs.js is disallowed and /jobs.json returns 406). Listing pages are server-rendered HTML; each job page carries JobPosting JSON-LD.
- **List:** `GET https://{company}.careerplug.com/jobs?page={n}`
- **Paging:** 30 jobs per page via ?page=N; collect href="/jobs/{id}" links
- **Detail:** `https://{company}.careerplug.com/jobs/{id} (redirects to /jobs/{id}/apps/new; that page holds JobPosting JSON-LD: datePosted, employmentType, identifier, baseSalary)`
- **Board token:** Company subdomain, e.g. 'midas-careers'. Dead or private subdomains redirect to app.careerplug.com/user/sign_in.
- **Own-domain sites:** CareerPlug also runs white-label domains listed in its robots sitemaps: apscareerportal.com, careinhomesjobs.com, r365hire.com, otrecruit.com. Franchise brands often use {brand}-careers.careerplug.com.
- **robots.txt:** User-Agent: * / Disallow: /apps/ /j/ /auth_results/ /attachments/ /manage/ /admin/ /jobs.js /account.js, plus Sitemap: https://s3.amazonaws.com/careerplug-sitemaps/careerplug_com/sitemap.xml.gz. /jobs and /jobs/{id} are allowed. The detail redirect lands on /jobs/{id}/apps/new; prefix matching does not catch that with '/apps/', but it is close to the rule's intent.
- **Blockers:** No bot wall seen. Plain detail requests land on an application-form URL (see robots note).
- **Notes:** The S3 sitemaps in robots.txt may list every job URL across tenants, which would avoid paginating. Not fetched. The Midas sample had employmentType OTHER and a 2020 datePosted (evergreen posting).
- **Live boards seen:** Midas (franchise careers) (30 on page 1, 44 pages (about 1,300) jobs), UFC GYM (30 on page 1, 16 pages (about 480) jobs)

### Comeet

- **Read via:** the platform's own JSON or XML interface. The public careers page embeds the full positions JSON (COMPANY_POSITIONS_DATA), with descriptions, in one GET. A token-based careers API also exists.
- **List:** `GET https://www.comeet.com/jobs/{company_slug}/{company_uid}`
- **Paging:** None; the whole array is inline (parse the JS literal after 'COMPANY_POSITIONS_DATA = ')
- **Detail:** `https://www.comeet.com/jobs/{company_slug}/{company_uid}/{position_slug}/{position_uid} (not needed; no JobPosting JSON-LD seen)`
- **Board token:** company slug + company UID in XX.XXX form, e.g. vastdata/43.001
- **Own-domain sites:** Employers embed the Comeet widget on their own careers pages (careers-api/api.js). You can tell it by comeet.com/jobs/{slug}/{uid} links or applynow.io apply emails.
- **robots.txt:** www.comeet.com and www.comeet.co: 'User-agent: * / Disallow: *?s=* */category/* /wp-admin/ /tag/ ... *?utm_*' and 'User-agent: Scrapy / Allow: /'. /jobs/ and /careers-api/ are allowed.
- **Blockers:** The official Careers API (GET https://www.comeet.co/careers-api/2.0/company/{uid}/positions?token={token}&details=true) needs a company token. One is printed in the careers-page HTML, but I did not call the API with it because the session's permission check blocked that request. The embedded page data needs no token.
- **Notes:** The pages are large (VAST Data is about 1.6 MB). There is no true posted date; use time_updated or first-seen.
- **Live boards seen:** VAST Data (266 jobs), Coralogix (58 jobs)

### CSOD

- **Read via:** the platform's own JSON or XML interface. The career-site shell embeds a regional API base and a public read JWT. The platform's own JSON search API returns requisitions with descriptions inline. Not verified live: I did not use the token.
- **List:** `POST {cloud}rec-job-search/external/jobs  (cloud from the page config, e.g. https://us.api.csod.com/ or https://eu-fra.api.csod.com/), header Authorization: Bearer {token from page csod.context}`
- **Request body:** `{"careerSiteId":{n},"pageNumber":1,"pageSize":100,"cultureId":{cultureID},"cultureName":"{cultureName}", ...}  (from third-party connector code; unverified)`
- **Paging:** pageNumber/pageSize until data.totalCount (reported by third-party code)
- **Detail:** `https://{tenant}.csod.com/ux/ats/careersite/{n}/home/requisition/{requisitionId}?c={tenant} (apply/view page, client-rendered)`
- **Board token:** Tenant subdomain + career site number, e.g. kohler + 16 (https://kohler.csod.com/ux/ats/careersite/16/home?c=kohler)
- **Own-domain sites:** Employers link to {tenant}.csod.com/ux/ats/careersite/{n}/home?c={tenant}. You can tell it by that path and the csod.context config with 'cloud' and 'token'.
- **robots.txt:** kohler.csod.com/robots.txt: 'User-agent: * / Crawl-delay: 10'. Nothing is disallowed, but keep requests at least 10 s apart per tenant host. us.api.csod.com/robots.txt returns a 404 JSON (no rules).
- **Blockers:** The listing API needs the anonymous bearer JWT embedded in the public page. I did not use it, by the same rule that blocked the Comeet token call. The owner should decide whether that is acceptable. If not, this platform is effectively 'html' via a JS-rendered SPA, i.e. blocked. Crawl-delay: 10.
- **Notes:** Endpoint shape and fields come from an open-source connector (strelov1/freehire internal/ingest/sources/cornerstone.go) and are not verified here. One token reportedly covers every career site of a tenant.
- **Live boards seen:** Kohler (shell page with token and cloud=us; jobs not fetched) (None jobs), GMV (shell page with token and cloud=eu-fra; jobs not fetched) (None jobs)

### Dayforce

- **Read via:** the platform's own JSON or XML interface. The Next.js candidate portal posts to a public JSON search API (no login; needs a NextAuth CSRF token and cookie). Job pages server-render the full posting in __NEXT_DATA__.
- **List:** `POST https://jobs.dayforcehcm.com/api/geo/{clientNamespace}/jobposting/search`
- **Request body:** `{"clientNamespace":"{clientNamespace}","jobBoardCode":"{jobBoardCode}","cultureCode":"en-US","distanceUnit":0,"paginationStart":0}  with header X-CSRF-TOKEN: {csrfToken} and the cookie from GET https://jobs.dayforcehcm.com/api/auth/csrf`
- **Paging:** paginationStart offset, 25 per page; maxCount is the total
- **Detail:** `https://jobs.dayforcehcm.com/en-US/{clientNamespace}/{jobBoardCode}/jobs/{jobPostingId} (HTML; __NEXT_DATA__ dehydratedState 'jobs' query has jobPostingContent.jobDescription HTML, postingLocations, jobPostingAttributes pay, timestamps)`
- **Board token:** clientNamespace + jobBoardCode from https://jobs.dayforcehcm.com/en-US/{clientNamespace}/{jobBoardCode}, e.g. copart/CANDIDATEPORTAL
- **Own-domain sites:** Usually linked directly to jobs.dayforcehcm.com. Some employers wrap it in their own careers page. You can tell it by that host or older {tenant}.dayforcehcm.com/CandidatePortal links.
- **robots.txt:** jobs.dayforcehcm.com/robots.txt has only Cloudflare content-signal comments: no User-agent or Disallow lines and no content-signal values. Nothing is disallowed.
- **Blockers:** POST without the CSRF token returns 403 'Forbidden'. Getting the token from /api/auth/csrf is the app's normal anonymous flow (no login, no challenge). The site is behind Cloudflare, but no challenge was served.
- **Notes:** List descriptions are cut at about 3.3k characters, so use the detail page for full text. Employment type is not a standard field; it may appear in jobPostingAttributes.
- **Live boards seen:** Prometric (112 jobs), WoodmenLife (30 jobs), Copart (5 jobs)

### Deel

- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). Boards are server-rendered with ItemList JSON-LD. Each job page has full JobPosting JSON-LD. Per-org sitemaps list every job. The JSON /api/ is disallowed by robots.txt.
- **List:** `GET https://jobs.deel.com/{orgSlug}/sitemap.xml (or the board page https://jobs.deel.com/{orgSlug}, which has ItemList JSON-LD of job URLs)`
- **Paging:** None; the sitemap or ItemList holds every job
- **Detail:** `https://jobs.deel.com/{orgSlug}/job-details/{uuid}/overview (JobPosting JSON-LD: title, description, datePosted, employmentType, jobLocation, identifier, url)`
- **Board token:** Org slug, e.g. 'klarna'. /job-boards/{slug} redirects to /{slug}.
- **Own-domain sites:** None seen; boards live on jobs.deel.com/{slug}
- **robots.txt:** 'User-agent: * / Allow: / / Disallow: /api/ / Disallow: /*/job-details/*/application' and a comment that per-org sitemaps are at /<orgSlug>/sitemap.xml. The board, sitemap and /overview pages are allowed; /api/ is not.
- **Blockers:** The JSON API is disallowed by robots.txt, so use JSON-LD.
- **Notes:** Check JSON-LD jobLocationType or applicantLocationRequirements for remote status. The Klarna sample showed neither field.
- **Live boards seen:** Deel (251 jobs), Klarna (82 jobs), SwingVision (5 jobs)

### Dover

- **Blocked:** the job data endpoints are disallowed by robots.txt; only job URLs are allowed
- **Read via:** blocked: ERIO does not crawl it (see the reason). Career pages are a client-rendered SPA with no server-side job data or JSON-LD. The JSON API under /api/ is disallowed by robots.txt on both jobs.dover.com and app.dover.com.
- **List:** `GET https://jobs.dover.com/feed/jobs_sitemap (allowed; job URLs only) — data endpoint https://app.dover.com/api/v1/careers-page/{id}/jobs is disallowed`
- **Paging:** The sitemap covers all boards (9,784 job URLs, 2,937 career pages in feed/careers_sitemap)
- **Detail:** `https://jobs.dover.com/{slug}/{uuid} (about 4 KB SPA shell: no content, no JSON-LD)`
- **Board token:** Company slug (jobs.dover.com/{slug}); job IDs are UUIDs
- **Own-domain sites:** Employers embed Dover career pages or link to jobs.dover.com/{slug} (also app.dover.com/jobs/{slug}).
- **robots.txt:** jobs.dover.com and app.dover.com: 'User-agent: * / Disallow: /.well-known/ /api/ /admin/django-admin/ /cal /hooks/ /lever /mcp /oauth/ /utils/' (jobs.dover.com adds 'Allow: /' and Sitemap: https://jobs.dover.com/feed/careers_sitemap index)
- **Blockers:** robots.txt disallows /api/; pages need JavaScript; the page loads Cloudflare Turnstile.
- **Notes:** The only robots-compliant data is the sitemap: URL, company slug, UUID and lastmod, with no title or description. Revisit if Dover adds JSON-LD or a public feed. Many Dover boards are recruiting agencies.
- **Live boards seen:** Xperteez (job URLs in sitemap) (286 jobs), Pontoon Global Solutions (job URLs in sitemap) (166 jobs), Her Campus Media (board page fetched: SPA shell only) (None jobs)

### Eightfold AI

- **Read via:** the platform's own JSON or XML interface. Career sites (PCS) call a public JSON search API; a per-position detail call returns the full HTML description
- **List:** `GET https://{tenant}.eightfold.ai/api/pcsx/search?domain={domain}&start={offset}&num=10`
- **Paging:** start/num offset, 10 per page; data.count gives total
- **Detail:** `https://{tenant}.eightfold.ai/api/pcsx/position_details?position_id={id}&domain={domain}`
- **Board token:** tenant subdomain + employer domain, e.g. paypal + paypal.com
- **Own-domain sites:** Large employers front it on their own domains (e.g. careers.qualcomm.com, jobs.careers.microsoft.com); recognise by /careers/job/{id} URLs and /api/pcsx/ calls with ?domain=
- **robots.txt:** paypal.eightfold.ai: 'User-agent: * / Disallow: / / Allow: /$ / Allow: /careers / Allow: /api/apply / Allow: /api/pcsx ...' plus 'Sitemap: https://paypal.eightfold.ai/careers/sitemap_index.xml?domain=paypal.com'. Listing and detail paths are explicitly allowed.
- **Notes:** Legacy /api/apply/v2/jobs?domain=paypal.com returned {"message": "Not authorized for PCSX"}, so use /api/pcsx/*. Unknown tenants (e.g. aexp) 404. Salary not seen. Employment-type field name varies per tenant. Big tenants mean one detail call per job: crawl incrementally.
- **Live boards seen:** PayPal (303 jobs), Vodafone (1234 jobs), Qualcomm (2072 jobs), Micron (2886 jobs)

### FirstStage

- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). No public API (first.cx disallows /api/); hosted board is server-rendered HTML listing role links, each role page has full JobPosting JSON-LD
- **List:** `GET https://{company}.firststage.co/jobs`
- **Paging:** none seen (all roles on one page); parse links matching /jobs/{roleId}/view
- **Detail:** `https://{company}.firststage.co/jobs/{roleId}/view (JSON-LD JobPosting)`
- **Board token:** company subdomain on firststage.co (role ids are 10-char alphanumerics like 2G4hL034TQ)
- **Own-domain sites:** Employers link out from their own sites (e.g. softwire.com -> softwire.firststage.co/roles/{id}/apply?source=softwire.com). Product rebranded to 'First' (first.cx); bare firststage.co redirects to first.cx, but company boards still live on {company}.firststage.co.
- **robots.txt:** {company}.firststage.co/robots.txt returns the app's 404 page (no robots file, so nothing is disallowed). first.cx/robots.txt: 'User-Agent: * / Allow: / / Disallow: /api/ ...' (do not use first.cx APIs).
- **Notes:** employmentType not present in the JSON-LD sampled. Closed /roles/{id} links 404. Small platform (aggregators report ~120 companies).
- **Live boards seen:** Reflexivity (9 jobs), Softwire (3 jobs), First (FirstStage itself) (1 jobs)

### Freshteam

- **Note:** Only one live board found (1 job); its JSON-LD swaps region and city
- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). robots.txt allows only /jobs; HTML list at /jobs plus JobPosting JSON-LD on each job page. A widget JSON (/hire/widgets/jobs.json) exists but robots disallows it
- **List:** `GET https://{company}.freshteam.com/jobs`
- **Paging:** none (single page); parse links /jobs/{jobKey}/{slug}
- **Detail:** `https://{company}.freshteam.com/jobs/{jobKey}/{slug} (JSON-LD JobPosting)`
- **Board token:** company subdomain on freshteam.com
- **Own-domain sites:** Employers can embed the jobs widget on their own sites. Recognise by assets.freshteam.com assets or *.freshteam.com/jobs links.
- **robots.txt:** All tenants (checked storeocean.freshteam.com): 'User-agent: * / Allow: /jobs / Allow: /.well-known/assetlinks.json / Disallow: /'. So /hire/widgets/jobs.json is DISALLOWED; /jobs and /jobs/* are allowed.
- **Blockers:** Widget JSON API blocked by robots.txt (I fetched it once before noticing; it returns {"jobs":[...]} with full descriptions; do not use it). Platform looks like it is shrinking: most tenants found by search or guessed (impact, maker, lotsquared, chargebee, zoominfo, gogoprint, datahut, ...) returned the 'We couldn't find' page or HTTP 500.
- **Notes:** Only ONE live board verified (giaspace, 1 job); no second live tenant found. JSON-LD quirk: addressRegion and addressLocality are swapped (Region='Fort Lauderdale', Locality='Florida'); datePosted is 'YYYY-MM-DD HH:MM:SS UTC'. Low priority.
- **Live boards seen:** GiaSpace Inc (1 jobs)

### Gem.com

- **Read via:** the platform's own JSON or XML interface. Gem documents a public Job Board API (no key) that returns all open posts with full HTML content in one call
- **List:** `GET https://api.gem.com/job_board/v0/{board}/job_posts/`
- **Paging:** none (whole board in one JSON array)
- **Detail:** `not needed (absolute_url = https://jobs.gem.com/{board}/{id})`
- **Board token:** job board vanity URL path (the slug in jobs.gem.com/{board})
- **Own-domain sites:** Employers may build their own careers page on the API, but apply links still go to jobs.gem.com/{board}/{postId}. Recognise by jobs.gem.com links or api.gem.com/job_board calls.
- **robots.txt:** jobs.gem.com/robots.txt returns a 404 page (no robots file). api.gem.com/robots.txt returns {"message":"Forbidden"} (no robots file). Nothing disallows the API.
- **Notes:** Unknown board returns 404 JSON 'Job board with vanity URL path X not found'. Shape is Greenhouse-like, so the Greenhouse mapper is a good template. Only Gem ATS customers have boards. No salary field (may appear in content).
- **Live boards seen:** Retool (25 jobs), Gem (1 jobs)

### GoHire

- **Note:** Only one populated board found, and it looks like a test account; every other board found is empty
- **Read via:** the platform's own JSON or XML interface. Board and widget call a public JSON endpoint keyed by the widget client id; descriptions need the server-rendered job page (no JSON-LD)
- **List:** `GET https://api2.gohire.io/widget-jobs/{clientId}`
- **Paging:** none (all jobs); optional filters remoteDdValue, typeDdValue, jobTitleSearched, cityOrCountrySearched
- **Detail:** `https://jobs.gohire.io/{companySlug}-{clientIdLower}/{jobSlug}-{jobId}/ (HTML only; no JSON-LD)`
- **Board token:** 8-char widget client id (e.g. 6oK69dA8), from the board URL suffix jobs.gohire.io/{slug}-{clientid}/ or the <script src=widget.gohire.io/widget/{clientId}> embed
- **Own-domain sites:** Employers embed widget.gohire.io/widget/{clientId} on their own sites; GoHire's own board is careers.gohire.io. Old URLs jobs.gohire.io/{slug}-{numericCompanyId}/ 301-redirect to the clientId form when the board is still live.
- **robots.txt:** jobs.gohire.io and careers.gohire.io: 'User-agent: * / Allow: /' (Sitemap: /sitemap.txt). api2.gohire.io/robots.txt returns a JSON 404 (no robots file).
- **Notes:** NOT fully verified: no live real-employer board with open jobs was found. jobs.gohire.io/sitemap.txt (17k URLs) is stale: it uses old numeric-id slugs and all 10 sampled company pages 404. Finding client ids is the hard part. Endpoint sends content-type text/html but the body is JSON.
- **Live boards seen:** Testify.ai (looks like a test/demo account) (282 jobs), GoHire (careers.gohire.io) (0 jobs), TeamUpdraft (0 jobs)

### Greenhouse

- First-release connector; endpoint and limits are in [sources.md](sources.md).

### HiBob

- **Read via:** the platform's own JSON or XML interface. The careers SPA calls GET /api/job-ad with a companyIdentifier header (the subdomain); one call returns every ad with full HTML sections
- **List:** `GET https://{company}.careers.hibob.com/api/job-ad  (request header 'companyIdentifier: {company}', which the public page itself sends; without it the API returns 401)`
- **Paging:** none (all ads in jobAdDetails[])
- **Detail:** `not needed; public job URL https://{company}.careers.hibob.com/jobs/{id}`
- **Board token:** company subdomain of careers.hibob.com
- **Own-domain sites:** None seen; careers pages are {company}.careers.hibob.com (Angular app served from front.hibob.com). HiBob's own jobs are not here (hibob.careers.hibob.com/api/job-ad returns 401).
- **robots.txt:** {company}.careers.hibob.com/robots.txt returns the SPA index.html (no robots file), so nothing is disallowed.
- **Notes:** The official HiBob Hiring API (api.hibob.com/v1/hiring/job-ads/search) needs a service-user API key, so it is not usable. The companyIdentifier header is not a credential: the public page's HTTP interceptor sets it from the hostname. Decode the response as UTF-8.
- **Live boards seen:** Gresham Technologies (43 jobs), Liquidia (22 jobs), Reward (10 jobs)

### HireBridge

- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). Server-rendered ASP.NET list page with all job ids; the v2 career-center detail page has JobPosting JSON-LD (the older JobDetails.aspx page has none)
- **List:** `GET https://recruit.hirebridge.com/v3/jobs/list.aspx?cid={cid}`
- **Paging:** none seen (Menard: 882 jobs on one page); parse JobDetails.aspx?cid={cid}&jid={jid} links
- **Detail:** `https://recruit.hirebridge.com/v3/careercenter/v2/details.aspx?jid={jid}&cid={cid} (JSON-LD JobPosting)`
- **Board token:** numeric company id cid (e.g. 5535); some boards add bid=1
- **Own-domain sites:** Employers link or iframe recruit.hirebridge.com from their own sites; recognise by recruit.hirebridge.com/v3/... ?cid= URLs.
- **robots.txt:** recruit.hirebridge.com: 'User-agent: * / Disallow: /application / Disallow: /company / Disallow: /jobseeker2 / Disallow: /jobseeker4'. /v3/jobs/ and /v3/careercenter/ are allowed.
- **Notes:** An invalid cid redirects to /v3/Application/AppErrMsg.aspx?errorType=badurl. Big boards need one detail request per job (Menard ~882), so throttle. Legacy /jobseeker2/index.asp boards are robots-disallowed.
- **Live boards seen:** Menard, Inc (882 jobs), IMC Construction (53 jobs), The Blaze Inc (0 jobs)

### HireHive

- **Read via:** the platform's own JSON or XML interface. Each hosted board exposes a public JSON jobs API with full HTML descriptions
- **List:** `GET https://{company}.hirehive.com/api/v1/jobs`
- **Paging:** nextPage field (null when done); publishedJobsCount gives total
- **Detail:** `not needed (hostedUrl = https://{company}.hirehive.com/{slug}-{shortId})`
- **Board token:** company subdomain on hirehive.com
- **Own-domain sites:** Employers can embed jobs on their own sites; hosted boards are {company}.hirehive.com. /api/v2/jobs also returns JSON (not inspected).
- **robots.txt:** focus-ireland.hirehive.com/robots.txt: 'User-agent: * / Disallow:' (empty, so everything is allowed).
- **Notes:** Board HTML also carries an ItemList JSON-LD. No separate remote field seen.
- **Live boards seen:** Focus Ireland (26 jobs), Catalyx (25 jobs)

### Hireology

- **Read via:** the platform's own JSON or XML interface. Public JSON careers API on api.hireology.com returns open jobs with full description, locations, remote flag and pay
- **List:** `GET https://api.hireology.com/v2/public/careers/{slug}?page_size=100&page={n}`
- **Paging:** page/page_size; response has count, page, page_size
- **Detail:** `not needed (career_site_url = https://careers.hireology.com/{slug}/{id}/description, which also has JobPosting JSON-LD with baseSalary)`
- **Board token:** career-site slug (careers.hireology.com/{slug})
- **Own-domain sites:** Some customers use their own domains. careers.hireology.com/sitemaps/sitemap-{n}.xml lists slugs and job URLs (50,000 URLs in sitemap-1), useful for discovery.
- **robots.txt:** careers.hireology.com: 'User-agent: * / Allow: /' (Sitemap: /sitemap_index.xml). api.hireology.com/robots.txt returns an HTML page (no robots file).
- **Notes:** The response also includes third_party_service_data (an Indeed Apply token); ignore it and do not store it. Hireology is strong in auto dealerships and healthcare: many small orgs.
- **Live boards seen:** Hireology (5 jobs), Nextpoint (2 jobs)

### HiringThing

- **Read via:** an RSS, Atom or XML job feed. Every hosted board links a public RSS feed with title, link, location and full HTML description; job pages add JSON-LD for the posted date
- **List:** `GET https://{company}.hiringthing.com/api/rss.xml`
- **Paging:** none (all open jobs)
- **Detail:** `https://{company}.hiringthing.com/job/{id}/{slug} (JSON-LD JobPosting: datePosted, location, hiringOrganization)`
- **Board token:** company subdomain on hiringthing.com
- **Own-domain sites:** HiringThing is white-labelled by HR/payroll partners, so boards may live on partner domains. The global sitemap index from robots.txt (https://s3.amazonaws.com/applicant-tracking-production-sitemap-us-east-1/sitemaps/applicant-tracking_sitemap.xml, 2,807 per-company sitemaps) lists tenants.
- **robots.txt:** hiringthing.com tenants: 'User-agent: * / SITEMAP: https://s3.amazonaws.com/.../applicant-tracking_sitemap.xml / Disallow: /admin'. /api/rss.xml and /job/* are allowed.
- **Notes:** The RSS has no pubDate and no employment type; fetch the JSON-LD only when posted_at is needed.
- **Live boards seen:** Structures Inc (8 jobs), Thomas Industrial Coatings (3 jobs)

### iCIMS

- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). No public JSON API; each portal publishes a sitemap.xml of all job URLs, and every job page has full JobPosting JSON-LD
- **List:** `GET https://{portal}.icims.com/sitemap.xml (alternative: https://{portal}.icims.com/jobs/search?ss=1&in_iframe=1&pr={page0} HTML, 20 per page)`
- **Paging:** sitemap: none; search HTML: pr=0..N ('Page 1 of 37')
- **Detail:** `https://{portal}.icims.com/jobs/{jobId}/{slug}/job?in_iframe=1 (JSON-LD JobPosting)`
- **Board token:** portal subdomain, usually careers-{company}; also jobs-{company}, uscareers-{company} etc.
- **Own-domain sites:** Very common: employers wrap the portal in an iframe on careers.company.com, or put it on a custom CNAME. Recognise by *.icims.com iframes or the /jobs/{id}/{slug}/job URL shape.
- **robots.txt:** careers-primehealthcare.icims.com: 'User-agent: * / Sitemap: .../sitemap.xml / Disallow: /jobs/*referral, /jobs/referral, /jobs/*login, /jobs/login, /jobs/*candidate, /jobs/candidate, /jobs/reminder, /connect...'. /jobs/search, /jobs/{id}/.../job and sitemap.xml are allowed.
- **Notes:** Sitemap counts include one /jobs/intro URL (job counts above already subtract it). Sitemap entries carry lastmod, good for incremental crawling. Many guessed portal names (careers-vca, careers-leidos, careers-uhs, ...) 404 or show 'gone', so tokens must come from employers' real links. Large portals mean thousands of detail requests: crawl incrementally by lastmod.
- **Live boards seen:** Prime Healthcare (3438 jobs), General Dynamics Mission Systems (736 jobs)

### iSolvedHire

- **Read via:** the platform's own JSON or XML interface. The career site's Vue widget calls a public JSON jobs endpoint; the full description comes from the job page JSON-LD (the platform is an ApplicantPro white-label)
- **List:** `GET https://{company}.isolvedhire.com/core/jobs/{domainId}?getParams={"isInternal":0}  (getParams is a URL-encoded JSON object; without it the response is not JSON)`
- **Paging:** none (data.jobs has all jobs; data.jobCount is the total)
- **Detail:** `https://{company}.isolvedhire.com/jobs/{jobId}.html (JSON-LD JobPosting with description, datePosted, employmentType, baseSalary)`
- **Board token:** company subdomain + numeric domainId (read once from 'domainId : N' in the /jobs/ page HTML)
- **Own-domain sites:** The same ApplicantPro platform also serves *.applicantpro.com boards. feeds.isolvedhire.com/site_map_index.xml lists 7,418 tenant sitemaps (https://{company}.isolvedhire.com/job_site_map.xml), useful for discovery.
- **robots.txt:** isolved.isolvedhire.com: 'User-agent: * / Disallow: /admin/ /stats/ /internaljobs/ /internaljobsbyorganization/ /internaljobsbyorganizationmap/ /internaljobsearch/' + 'Sitemap: https://feeds.isolvedhire.com/site_map_index.xml'. /core/jobs and /jobs/*.html are allowed.
- **Notes:** Keep isInternal=0 (internal job routes are robots-disallowed). The page also contains a job-alert widget API key; it is not needed and was not used. The per-tenant job_site_map.xml is an alternative listing source.
- **Live boards seen:** isolved (36 jobs), Shields Business Solutions (6 jobs)

### JazzHR

- **Note:** A feed over the 10 MB response cap (Crunch Fitness, 843 jobs) cannot be read; boards are listed in app.jazz.co's public sitemaps
- **Read via:** an RSS, Atom or XML job feed. Public per-account XML job feed on app.jazz.co returns every open job with full HTML description in one request
- **List:** `GET https://app.jazz.co/feeds/export/jobs/{subdomain}`
- **Paging:** none, one document with all open jobs
- **Detail:** `https://{subdomain}.applytojob.com/apply/{jobCode}/{slug} (HTML with schema.org JobPosting JSON-LD: datePosted, employmentType, baseSalary)`
- **Board token:** applytojob.com subdomain, e.g. brennancenter, crunchfitness
- **Own-domain sites:** Career pages are {subdomain}.applytojob.com; employers embed the JazzHR widget on their own sites, recognisable by links to *.applytojob.com/apply/{10-char code}/. Global sitemaps http://app.jazz.co/feeds/google/xml/0..4 list every live job URL across all customers (useful for board discovery).
- **robots.txt:** app.jazz.co and *.applytojob.com: 'User-agent: * / Disallow: /cb' (only SemrushBot and dotbot fully disallowed). /feeds and /apply allowed.
- **Notes:** Feed elements per <job>: id, internalcode, status, title, department, url, city, state, country, postalcode, description (CDATA HTML), type, experience, buttons. No posted date or remote flag in the feed. The feed's <url> is the apply URL.
- **Live boards seen:** Crunch Fitness - CR Holdings (843 jobs), Brennan Center for Justice (23 jobs)

### Jobvite

- **Read via:** the job pages' HTML (no feed or structured data). jobs.jobvite.com career sites are server-rendered HTML with all jobs on one page; no JSON-LD and no public JSON API found
- **List:** `GET https://jobs.jobvite.com/{company}/jobs`
- **Paging:** none observed, all jobs in one page (Nutanix 131 jobs on one page)
- **Detail:** `https://jobs.jobvite.com/{company}/job/{jobId} (HTML: h2.jv-header title, .jv-job-detail-meta category/location/Req.Num, .jv-job-detail-description)`
- **Board token:** company slug, e.g. nutanix, egnyte; job IDs are 8-char alphanumerics like oSK3AfwZ
- **Own-domain sites:** Some employers embed the Jobvite HostedJobs widget on their own sites; recognise links to jobs.jobvite.com/{company}/job/ or the jv- CSS class prefix.
- **robots.txt:** jobs.jobvite.com/robots.txt returns 404 (no restrictions). app.jobvite.com robots disallows /API/, /Jobs/, /Careers/ and many app paths, but not /CompanyJobs/ apart from /CompanyJobs/PreviewApplication.aspx.
- **Blockers:** No public JSON. An XML job feed exists (https://app.jobvite.com/CompanyJobs/Xml.aspx?c={companyId}) only when the customer enables it and needs a company ID that is not shown on the career site; not verified.
- **Notes:** List rows: a.jv-job-list-name links /{company}/job/{id}, td.jv-job-list-location. No posted date or employment type on the listing; detail page shows Req.Num and category but no JSON-LD date. Several guessed slugs (logitech, zillow, ringcentral) 302 away, meaning those employers left Jobvite.
- **Live boards seen:** Nutanix (131 jobs), Egnyte (24 jobs)

### JOIN.com

- **Read via:** the platform's own JSON or XML interface. Public JSON API used by the join.com company page lists jobs with salary, workplace type and created date
- **List:** `GET https://join.com/api/public/companies/{companyId}/jobs?page={n}&pageSize=5`
- **Paging:** page/pageSize; pageSize=5 accepted, 10/20/50 rejected with 422; response has pagination.pageCount
- **Detail:** `https://join.com/companies/{slug}/{idParam} (HTML with schema.org JobPosting JSON-LD incl. description, datePosted, employmentType, baseSalary; old idParams 301 to the current one)`
- **Board token:** company slug (join.com/companies/{slug}); numeric companyId is read from __NEXT_DATA__ props.pageProps.initialState.company.id on the company page
- **Own-domain sites:** Employers embed a JOIN jobs widget on their own sites; recognise links to join.com/companies/{slug}/{id}-{title}.
- **robots.txt:** User-agent: * / Disallow: /*/lp/ ; sitemaps: https://join.com/companies/sitemap.xml (14,322 company URLs), https://join.com/companies/sitemap-jobs-index.xml. /api and /companies are not disallowed.
- **Blockers:** Cloudflare: after about 6 requests in a few seconds join.com returned an 'Attention Required' challenge page (sitemap-jobs-index.xml). It cleared later. Connector must go slowly.
- **Notes:** The company page __NEXT_DATA__ also carries the first page of jobs (initialState.jobs.items + pagination), so one HTML request gives companyId and page 1.
- **Live boards seen:** JOIN (5 jobs), bring (4 jobs)

### Kula.ai

- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). careers.kula.ai/{company} is server-rendered with job links; each job page has full JobPosting JSON-LD. The internal /api/ is disallowed in robots.txt
- **List:** `GET https://careers.kula.ai/{company}`
- **Paging:** none observed, all jobs on one page (Rocketlane 45)
- **Detail:** `https://careers.kula.ai/{company}/{jobId}-{slug} (JobPosting JSON-LD: datePosted, employmentType, description)`
- **Board token:** company slug, e.g. rocketlane, deepscribe; job links /{company}/{numericId}-{slug}
- **Own-domain sites:** Kula pages are on careers.kula.ai; assets from careers-cdn.kula.ai. Custom-domain hosting not observed.
- **robots.txt:** User-Agent: * / Allow: / / Disallow: /api/ / Disallow: /*/portal$ / Disallow: /*/portal/
- **Notes:** The listing page's Next.js RSC payload (self.__next_f) embeds a JSON array of jobs with id, title, launch_at, employment_type, workplace, department and offices (city/state/country/remote), with descriptions as $ references. Parseable but tied to the Next.js build, so prefer links + JSON-LD. Sitemap at a hashed name (sitemap-index-*.xml) is linked from the page.
- **Live boards seen:** Rocketlane (45 jobs), DeepScribe (5 jobs)

### Lever.co

- First-release connector; endpoint and limits are in [sources.md](sources.md).

### Manatal

- **Read via:** the platform's own JSON or XML interface. Public open career-page JSON API returns all published jobs with full HTML descriptions, paginated
- **List:** `GET https://core.api.manatal.com/open/v3/career-page/{slug}/jobs/?page={n}&page_size=100`
- **Paging:** page/page_size, DRF-style count/next/previous (api.manatal.com redirects to core.api.manatal.com)
- **Detail:** `https://www.careers-page.com/{slug}/job/{hash} (HTML, no JobPosting JSON-LD found)`
- **Board token:** career page slug (username), e.g. talentrecruit, job-expert-thailand-co-ltd
- **Own-domain sites:** Hosted at careers-page.com/{slug} (newer 'Advanced Career Page' on custom subdomains, plus iframes on employer sites). Recognise by careers-page.com links or manatal-backend-static assets.
- **robots.txt:** careers-page.com/robots.txt, api.manatal.com/robots.txt and core.api.manatal.com/robots.txt all 404 (no restrictions).
- **Notes:** No posted date in the open API. Many boards are recruitment agencies posting for clients (organization_name per job).
- **Live boards seen:** Talent Recruit (Malaysia) (747 jobs), Job Expert Thailand (527 jobs), Hyred APAC (16 jobs), Manatal (demo, manatal3) (27 jobs)

### Oracle Recruiting

- **Read via:** the platform's own JSON or XML interface. Candidate Experience sites call a public HCM REST endpoint that returns JSON without login
- **List:** `GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber={siteNumber},limit=25,offset={n},sortBy=POSTING_DATES_DESC`
- **Paging:** offset/limit in the finder string; items[0].TotalJobsCount gives the total
- **Detail:** `https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?expand=all&onlyData=true&finder=ById;Id="{Id}",siteNumber={siteNumber}`
- **Board token:** host ({pod}.fa.{region}.oraclecloud.com, e.g. jpmc.fa.oraclecloud.com, eeho.fa.us2.oraclecloud.com) + site number (CX_1001, CX_45001)
- **Own-domain sites:** Career site is https://{host}/hcmUI/CandidateExperience/en/sites/{siteNumber}/; employers link to it from their own domains. Apply URL: https://{host}/hcmUI/CandidateExperience/en/sites/{siteNumber}/job/{Id}.
- **robots.txt:** jpmc.fa.oraclecloud.com/robots.txt returned 403 'W4S-402: Blocked by WAF4SaaS' to our client (robots could not be read); eeho.fa.us2.oraclecloud.com/robots.txt is 404 (no restrictions).
- **Blockers:** Oracle's WAF4SaaS blocked the robots.txt fetch on one tenant (403), while the REST API answered 200. Treat robots as unknown on such tenants and keep requests light.
- **Notes:** List gives ShortDescriptionStr only. Salary is not in the standard fields seen; some tenants may put it in flex fields or the description.
- **Live boards seen:** JPMorgan Chase (7164 jobs), Oracle (2802 jobs)

### PageUp

- **Read via:** an RSS, Atom or XML job feed. Every PageUp career site has an RSS feed with all jobs, full HTML description, location, work type, closing date and apply link
- **List:** `GET https://careers.pageuppeople.com/{instanceId}/cw/{locale}/rss`
- **Paging:** none, all jobs in one feed (MSU 466 items)
- **Detail:** `https://careers.pageuppeople.com/{instanceId}/cw/{locale}/job/{jobId}/{slug} (HTML, no JSON-LD; open-date/close-date in <time datetime>)`
- **Board token:** numeric instance ID + locale, e.g. 782/en-us (Michigan State University), 513/en (Monash University)
- **Own-domain sites:** Some customers front it with their own domain or embed it; recognise careers.pageuppeople.com/{id}/cw/ links and apply links to secure.dc{n}.pageuppeople.com/apply/{id}/.
- **robots.txt:** User-agent: * with Disallow for /admin, /awake, /uat, /cwuat, /ciuat, /ci, /uatinternal, /testint, /staging and /*/ci/, /*/uat/ etc. Public /{id}/cw/ paths are allowed; /{id}/ci/ (internal job boards) are disallowed.
- **Notes:** Feed self-link is .../latest_jobs.rss. HTML listing paginates 20 at a time via /listing/?page={n}&page-items=20 (returns JSON with HTML fragment) if the feed is ever missing. Instance 690 returned 404, so not every ID exists.
- **Live boards seen:** Michigan State University (466 jobs), Monash University (69 jobs)

### Paradox

- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). Paradox Career Site Studio sites expose per-site job sitemaps and JobPosting JSON-LD on each job page; no public listing API found
- **List:** `GET https://{careerSiteHost}/sitemap.xml (sitemap index -> sitemap-{hash}-{lang}.xml files listing /{slug}/job/{32-hex id} URLs)`
- **Paging:** sitemap index with several sub-sitemaps
- **Detail:** `https://{careerSiteHost}/{slug}/job/{32-hex jobId} (JobPosting JSON-LD: title, description, datePosted, identifier, location)`
- **Board token:** career site hostname (employer's own domain, e.g. www.essentiacareers.org, careers.marriott.com)
- **Own-domain sites:** All Paradox career sites run on the employer's own domain. Recognise them by assets from cdn.sites.paradox.ai (paths /paradox-prod-careersites/ and /common-libraries/), an olivia.paradox.ai chat widget, and job URLs ending /job/{32 hex chars}.
- **robots.txt:** www.essentiacareers.org: 'User-agent: *' with no Disallow. careers.marriott.com: 'User-Agent: *' plus 'Sitemap: https://careers.marriott.com/sitemap.xml', no Disallow.
- **Notes:** Marriott's sitemap index has 23 sub-sitemaps (several languages); 344 is the count in one English sub-sitemap, not the site total. The /jobs HTML page shows 10 jobs per page via a React pagination widget. careers.paradox.ai itself now redirects to Workday (Paradox was acquired by Workday). Paradox is also often only a chat/apply layer on top of another ATS (e.g. jobs.chipotle.com runs on Radancy), so detect by the cdn.sites.paradox.ai fingerprint, not by the brand.
- **Live boards seen:** Essentia Health (759 jobs), Marriott International (344 jobs)

### Paycom

- **Note:** job lists load with a session token the career page issues each visitor; using it needs the owner's decision
- **Read via:** blocked: ERIO does not crawl it (see the reason). Job pages carry JobPosting JSON-LD, but the job list is loaded by a JavaScript app from /api/ats/job-postings with a session JWT minted into the page; no token-free list or feed found
- **List:** `GET https://www.paycomonline.net/v4/ats/web.php/portal/{clientKey}/career-page (HTML shell only; jobs come from /api/ats/job-postings/ with a Bearer sessionJWT from configsFromHost)`
- **Paging:** unknown (not called)
- **Detail:** `https://www.paycomonline.net/v4/ats/web.php/portal/{clientKey}/jobs/{jobId} (JobPosting JSON-LD: title, datePosted, description)`
- **Board token:** 32-hex client key, e.g. 3E7E5ADB1EDBD6EE6581646E848F89D8
- **Own-domain sites:** Employers link or iframe the paycomonline.net portal from their own sites; recognise /v4/ats/web.php/portal/{32 hex}/.
- **robots.txt:** User-agent: * / Disallow: / with Allow: /v4/ats/sitemap.php, /v4/ats/web.php/portal/, /api/ats/job-postings/, /api/ats/company-name, /api/ats/portal-settings, /career-portal/sprawl.json and the portal JS/CSS. So portal pages and the job-postings API are allowed to crawlers.
- **Blockers:** The listing API needs the per-visit sessionJWT embedded in the career-page HTML. It is anonymous (no login), but it is a token, so I did not call the API; needs an owner decision. Unauthenticated GET /api/ats/job-postings/ returns a 'Paycom Disruption' HTML page. /v4/ats/sitemap.php returned 404. Job counts for the examples were not obtainable.
- **Notes:** If the owner accepts using the page-issued anonymous session token (the same one every visitor's browser receives), this becomes 'dedicated'. Otherwise only individual job URLs found elsewhere can be read via JSON-LD.
- **Live boards seen:** Unknown employer (portal from a ZipRecruiter link) (0 jobs), Duluth, MN nonprofit (case management) (1 jobs)

### Paycor

- **Blocked:** robots.txt on recruitingbypaycor.com disallows everything
- **Read via:** blocked: ERIO does not crawl it (see the reason). recruitingbypaycor.com robots.txt disallows all crawling
- **List:** `GET https://recruitingbypaycor.com/career/CareerHome.action?clientId={clientId} (not fetched)`
- **Paging:** n/a
- **Detail:** `https://recruitingbypaycor.com/career/JobIntroduction.action?clientId={clientId}&id={jobId}&lang=en (not fetched)`
- **Board token:** 32-hex clientId, e.g. 8a7883c66e1f22fa016e6b8f65563df5 (Advanced Cooling Technologies, from search results)
- **Own-domain sites:** Employers iframe or link recruitingbypaycor.com career pages from their own sites (Paycor Recruiting, formerly Newton ATS; Paycor now owned by Paychex).
- **robots.txt:** https://recruitingbypaycor.com/robots.txt: 'User-agent: * / Disallow: /'
- **Blockers:** robots.txt Disallow: / for all agents. Nothing beyond robots.txt was fetched. Paycor's newer product (Paycor Recruiting on JazzHR) uses applytojob.com, which the JazzHR connector covers.
- **Notes:** Legacy Newton ATS had an Atom feed (CareerAtomFeed.action?clientId=...), but it is on the same disallowed host.
- **Live boards seen:** Advanced Cooling Technologies (0 jobs), Brooklyn Museum (per Tessitura job board link) (0 jobs)

### Paylocity

- **Read via:** the platform's own JSON or XML interface. The public jobs page embeds a window.pageData JSON object with every job (id, title, location, published date, remote flag); job pages carry JobPosting JSON-LD for full descriptions
- **List:** `GET https://recruiting.paylocity.com/recruiting/jobs/All/{companyGuid}`
- **Paging:** none, all jobs in pageData.Jobs
- **Detail:** `https://recruiting.paylocity.com/Recruiting/Jobs/Details/{JobId} (JobPosting JSON-LD incl. datePosted and description)`
- **Board token:** company GUID, e.g. ff517f63-c379-48fb-acc8-8d66e8d5b076
- **Own-domain sites:** Employers embed the Paylocity careers widget or link to recruiting.paylocity.com/recruiting/jobs/All/{guid}/{name}; recognise by that host and GUID.
- **robots.txt:** recruiting.paylocity.com/robots.txt returns 404 (no restrictions).
- **Notes:** Parse with regex window.pageData = {...}; then JSON. Skip jobs with IsInternal=true. /recruiting/v2/api/feed/jobs/{guid} answers 200 but returned jobs:[] for a board with 57 jobs, so do not rely on it.
- **Live boards seen:** Louisiana CAT (57 jobs), Howard Lake, MN food processor (page title 'ALL JOBS') (34 jobs), Yes& Companies (0 jobs)

### Personio

- **Read via:** an RSS, Atom or XML job feed. Every Personio career site serves a public XML feed of all open positions, with descriptions when the employer fills them
- **List:** `GET https://{company}.jobs.personio.de/xml?language={en/de}`
- **Paging:** none, all positions in one document
- **Detail:** `https://{company}.jobs.personio.de/job/{id}?language=en (HTML; no JobPosting JSON-LD found)`
- **Board token:** company subdomain, e.g. 1komma5grad, join; .jobs.personio.com also works
- **Own-domain sites:** Some employers proxy or embed the Personio page on their own domain; recognise by *.jobs.personio.de/.com links or the <workzag-jobs> XML root.
- **robots.txt:** User-agent: * / Allow: /
- **Notes:** Unknown subdomains return a 404 HTML 'Page Not Found'; a valid company with no jobs returns an empty <workzag-jobs/>. No salary or remote flag in the feed (remote sometimes appears in office names, e.g. 'Berlin (Remote)'). Many big names (taxfix, forto, sumup, raisin) were not on Personio.
- **Live boards seen:** 1KOMMA5° (324 jobs), JOIN GmbH (Join Solutions) (2 jobs)

### Phenom People

- **Read via:** the platform's own JSON or XML interface. Phenom career sites call a public JSON endpoint (POST /widgets, ddoKey refineSearch) and also embed the first page of results as JSON (phApp.ddo) in the search page
- **List:** `POST https://{careerHost}/widgets`
- **Request body:** `{"lang":"en_global","deviceType":"desktop","country":"global","pageName":"search-results","ddoKey":"refineSearch","sortBy":"","subsearch":"","from":0,"jobs":true,"counts":true,"all_fields":["category","country","state","city","type"],"size":10,"clearAll":false,"jdsource":"facets","isSliderEnable":false,"pageId":"page20","siteType":"external","keywords":"","global":true,"selected_fields":{},"locationData":{}}`
- **Paging:** from/size offset (size 10 used by the site); refineSearch.totalHits gives the total. Fallback: GET https://{careerHost}/{country}/{lang}/search-results?from={n}&s=1 embeds the same refineSearch result in phApp.ddo (eagerLoadRefineSearch)
- **Detail:** `https://{careerHost}/{country}/{lang}/job/{jobId}`
- **Board token:** career host + locale path (country/lang, e.g. global/en or us/en); lang/country in the POST body must match the site's locale
- **Own-domain sites:** Always on the employer's own domain (jobs.thermofisher.com, careers.tranetechnologies.com). Recognise by 'phApp.ddo' / 'phApp.baseUrl' in the HTML, assets from assets.phenompeople.com, and URLs like /{country}/{lang}/search-results and /{country}/{lang}/job/{id}
- **robots.txt:** jobs.thermofisher.com: User-agent: * with 'Disallow: */apply', 'Disallow: */jobcart', 'Disallow: */px-widgets' plus per-locale sitemaps; nothing disallows /widgets, /search-results or /job/. careers.tranetechnologies.com: User-agent: * 'Disallow: */px-widgets' only
- **Notes:** List items include jobId, reqId, title, location/city/state/country, multi_location, category, type (e.g. 'Full time'), postedDate, dateCreated, applyUrl (often the employer's underlying ATS such as Workday). Remote is not a dedicated field; infer from location/title. Salary only when a site maps a field (Thermo shows 'reward').
- **Live boards seen:** Thermo Fisher Scientific (3243 jobs), Trane Technologies (1717 jobs)

### Pinpoint

- **Read via:** the platform's own JSON or XML interface. Every Pinpoint career site serves all open postings as one public JSON document at /postings.json with full HTML descriptions
- **List:** `GET https://{token}.pinpointhq.com/postings.json`
- **Paging:** none; one response returns every posting (171 for Innovetive Petcare)
- **Detail:** `https://{token}.pinpointhq.com/en/postings/{uuid}`
- **Board token:** Subdomain of pinpointhq.com (e.g. made-tech, workwithus)
- **Own-domain sites:** Not observed; all checked boards live on {token}.pinpointhq.com
- **robots.txt:** User-Agent: * / Disallow: /mydata / Disallow: /admin / Disallow: /companies -- /postings.json and /en/postings/ are allowed
- **Notes:** Each item: id, title, url, path, description + key_responsibilities + skills_knowledge_expertise + benefits (HTML sections, concatenate), employment_type ('full_time'), workplace_type ('remote'/'hybrid'/'onsite'), location {city, name, province, postal_code}, job {requisition_id, department}, compensation_minimum/maximum/currency/frequency/visible, deadline_at. No posted date in postings.json.
- **Live boards seen:** Pinpoint (own board) (6 jobs), Made Tech (28 jobs), Innovetive Petcare (171 jobs)

### Polymer

- **Read via:** the platform's own JSON or XML interface. Public JSON API at api.polymer.co lists an organisation's jobs; per-job endpoint returns the full description
- **List:** `GET https://api.polymer.co/v1/hire/organizations/{token}/jobs`
- **Paging:** page-based; meta {page, next_page, is_last, total, count}; follow next_page (?page=N assumed, not exercised: tested boards fit on one page)
- **Detail:** `https://api.polymer.co/v1/hire/organizations/{token}/jobs/{id}`
- **Board token:** Organisation slug from https://jobs.polymer.co/{slug}
- **Own-domain sites:** Not observed; boards are https://jobs.polymer.co/{slug} with jobs at /{slug}/{id}
- **robots.txt:** jobs.polymer.co/robots.txt is empty (200, 0 bytes); api.polymer.co/robots.txt returned an empty body -- nothing disallowed
- **Notes:** List items: id, hash_id, title, country, state_region, city, display_location, kind_pretty ('Full-time'/'Contract'), published_at, job_post_url, remoteness_pretty ('Remote'), salary_pretty ('51,800 - 66,900 USD a year'), remote_restriction_*. Unknown slug returns 422 {"errors":{"organization":["could not be found"]}}. Job pages on jobs.polymer.co also carry JobPosting JSON-LD with structured baseSalary. jobs.polymer.co is behind Cloudflare but served plain curl fine.
- **Live boards seen:** Invicta Software (4 jobs), Bladework Games (1 jobs)

### Recooty

- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). No public JSON/RSS feed; hosted board lists job links in HTML (10 per page) and each job page has schema.org JobPosting JSON-LD
- **List:** `GET https://jobs.recooty.com/{token}?page={n}`
- **Paging:** ?page=N, about 10 jobs per page; stop when no new /{token}/ job links appear
- **Detail:** `https://jobs.recooty.com/{token}/{job-slug}`
- **Board token:** Company slug on jobs.recooty.com (e.g. gibbons-group)
- **Own-domain sites:** Employers can embed a Recooty widget or WordPress plugin on their own site; also seen domains.recooty.com/{slug}/... (returned HTTP 530 when tested). Recognise by links to jobs.recooty.com
- **robots.txt:** jobs.recooty.com: 'User-agent: *' / 'Disallow:' (empty) -- everything allowed
- **Blockers:** Laravel rate limit behind Cloudflare: X-RateLimit-Limit 120; our first request got HTTP 429 with Retry-After 4 (counter looked shared/IP-wide). Must throttle and honour Retry-After. jobs.recooty.com/recooty and /shine returned 404 (boards removed).
- **Notes:** The root https://jobs.recooty.com/ is a cross-employer job board (?page=1..230) usable to discover company slugs. Remote and salary not seen in JSON-LD.
- **Live boards seen:** Gibbons Group (10 on page 1; pagination links to page 8+ jobs), Davis Cartage Company (10 on page 1; 2 pages jobs)

### Recruitee

- First-release connector; endpoint and limits are in [sources.md](sources.md).

### Rippling

- **Read via:** the platform's own JSON or XML interface. Public JSON board API on api.rippling.com backs ats.rippling.com boards; detail endpoint has the full description
- **List:** `GET https://api.rippling.com/platform/api/ats/v1/board/{token}/jobs`
- **Paging:** none; returns the full array (47 jobs for rts)
- **Detail:** `https://api.rippling.com/platform/api/ats/v1/board/{token}/jobs/{uuid}`
- **Board token:** Board slug from https://ats.rippling.com/{slug}/jobs
- **Own-domain sites:** Some companies redirect their slug elsewhere (ats.rippling.com/rippling/jobs -> 307 to rippling.com/careers). Recognise boards by ats.rippling.com/{slug}/jobs/{uuid} links
- **robots.txt:** ats.rippling.com: 'User-agent: *' / 'Disallow: /internal/'. api.rippling.com/robots.txt returns 404 (no rules)
- **Notes:** List item: uuid, name, department, url, workLocation {label}. Detail: description {company, role} (two HTML parts), workLocations[], employmentType {label 'SALARIED_FT', id 'Salaried, full-time'}, createdOn, payRangeDetails[], companyName. Remote only via location label (e.g. 'Remote (United States)').
- **Live boards seen:** Skillable (4 jobs), RTS (47 jobs), Routeware (3 jobs)

### Rival

- **Note:** robots.txt asks for a 10-second crawl delay, so a full crawl is slow
- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). Rival is the renamed SilkRoad; hosted boards on jobs.silkroad.com list jobs in HTML and each job page has JobPosting JSON-LD; robots asks for Crawl-delay 10
- **List:** `GET https://jobs.silkroad.com/{token}/Careers?page={n}`
- **Paging:** ?page=N, 10 job links per page
- **Detail:** `https://jobs.silkroad.com/{token}/Careers/jobs/{id}`
- **Board token:** Tenant path segment on jobs.silkroad.com (e.g. SOCCo, tvcca; case-insensitive)
- **Own-domain sites:** Legacy OpenHire 'ePostings' sites at {tenant}.silkroad.com/epostings/index.cfm?fuseaction=app.welcome&company_id=N are closed to crawlers (robots 'Disallow: /'). No public board found on a rival-hr.com host
- **robots.txt:** jobs.silkroad.com: 'User-agent: *' 'Crawl-Delay: 10' with Disallow for /bin/, /Content/, /Scripts/, /Views/, /*/*/Ajax/ etc. -- /{tenant}/Careers allowed. southland.silkroad.com (ePostings): 'User-agent: *' 'Disallow: /'
- **Blockers:** Crawl-delay 10s on jobs.silkroad.com; legacy ePostings hosts fully disallowed
- **Notes:** No JSON/RSS feed found. The /*/*/Ajax/ paths the page uses are disallowed, so stick to HTML + JSON-LD.
- **Live boards seen:** SOCCo (10 on page 1, 2+ pages jobs), TVCCA (10 on page 1 jobs)

### SAP SuccessFactors

- **Read via:** the job pages' HTML (no feed or structured data). CSB sites list every job URL in an allowed /sitemap.xml and job pages carry schema.org JobPosting microdata (not JSON-LD); the RSS feed under /services/ is disallowed by robots
- **List:** `GET https://{careerHost}/sitemap.xml`
- **Paging:** none; one urlset (1537 URLs on jobs.bombardier.com) or, on some sites, a Google Base RSS document with every job and full description (jobs.deere.com, 388 items)
- **Detail:** `https://{careerHost}/{optional-brand}/job/{City-Title-slug}/{jobId}/`
- **Board token:** Employer career host (CSB is always on the employer's domain, e.g. jobs.ball.com)
- **Own-domain sites:** All CSB sites are on employer domains (jobs.<company>.com / careers.<company>.com). Recognise by robots.txt 'Disallow: /services/' + '/talentcommunity/', job URLs /job/{slug}/{numericId}/, '/go/{category}/{id}/' pages, a sitemap using the sitemapssl.xsl stylesheet, rmkcdn.successfactors.com assets
- **robots.txt:** jobs.deere.com: 'User-agent: *' ... 'Disallow: /services/' (also /applybutton/, /talentcommunity/, /preapply/). jobs.ball.com and jobs.bombardier.com: 'User-agent: *' 'Disallow: /services/'. Sitemap and /job/ pages allowed. jobs.sap.com is no longer CSB (Next.js; /services/rss now 404).
- **Blockers:** The known RSS feed https://{host}/services/rss/job/?locale=en_US&keywords= exists (20 items on jobs.deere.com; I fetched it once before reading robots) but /services/ is disallowed in the standard CSB robots.txt, so do not use it. Sitemap may include non-job pages: keep only /job/ URLs.
- **Notes:** One detail request per job. Employment type and remote were not in the microdata on jobs.ball.com. Legacy Recruiting Management URLs (career{N}.successfactors.com/career?company=...) were not tested.
- **Live boards seen:** Ball Corporation (240 jobs), Bombardier (1537 sitemap URLs (may include non-job pages) jobs), John Deere (388 jobs)

### SmartRecruiters

- **Blocked:** robots.txt turns away every crawler except LinkedIn's
- First-release connector; endpoint and limits are in [sources.md](sources.md).

### talentReef

- **Note:** jobs come only from an internal-looking search host; whether it is meant for public use needs the owner's decision
- **Read via:** blocked: ERIO does not crawl it (see the reason). Career sites are a client-side React app with no server HTML, JSON-LD or sitemap; the data comes from an Elasticsearch proxy on an 'internal'-named talentreef.com host that I did not query, so there is no verified public feed
- **List:** `GET Not verified. The app bundle (apply.jobappnetwork.com/static/js/main.*.js) builds POST https://prod-kong.internal.talentreef.com/apply/proxy-es/search-en-us/posting/_search with a filter on clientId.raw`
- **Detail:** `Hosted page https://apply.jobappnetwork.com/clients/{clientId}/posting/{postingId}/en is an empty SPA shell`
- **Board token:** Numeric clientId (e.g. 14637 for DHL) or a vanity slug (apply.jobappnetwork.com/talentreef); legacy cf-apply.jobappnetwork.com/apply/c_{code}/l_en/... URLs redirect to the new paths
- **Own-domain sites:** Employers link to apply.jobappnetwork.com / cf-apply.jobappnetwork.com / secure.jobappnetwork.com; recognise by those hosts
- **robots.txt:** apply.jobappnetwork.com: 'User-agent: *' 'Disallow:' (empty, all allowed). cf-apply.jobappnetwork.com/robots.txt 404. prod-kong.internal.talentreef.com not checked
- **Blockers:** No server-rendered content; the only data source is a backend on a host named *.internal.talentreef.com. My tool permissions refused probing it as possible access circumvention, so it is unverified whether it is meant for public use. Needs a human decision before any connector.
- **Notes:** Bundle shows posting index fields: positionType, category, description, address, jobId, clientId, clientName, brand, location, url, postingUuid, isSalaried, minCompensation, maxCompensation, pubCompensation. Hourly-worker employers (restaurants, retail, logistics) usually also post to Indeed etc.
- **Live boards seen:** talentReef (unknown (SPA, 1 KB shell) jobs), DHL Supply Chain (unknown (SPA) jobs)

### Taleo

- **Read via:** the platform's own JSON or XML interface. Taleo career sections call a public JSON search endpoint (POST /careersection/rest/jobboard/searchjobs) used by the jobsearch.ftl page
- **List:** `POST https://{tenant}.taleo.net/careersection/rest/jobboard/searchjobs?lang=en&portal={portalNo}`
- **Request body:** `{"multilineEnabled":false,"sortingSelection":{"sortBySelectionParam":"3","ascendingSortingOrder":"false"},"fieldData":{"fields":{"KEYWORD":"","LOCATION":"","CATEGORY":""},"valid":true},"filterSelectionParam":{"searchFilterSelections":[]},"advancedSearchFiltersSelectionParam":{"searchFilterSelections":[]},"pageNo":1}  (headers: Content-Type: application/json, tz: GMT-05:00)`
- **Paging:** pageNo 1..n, pageSize 25; pagingData.totalCount gives the total
- **Detail:** `https://{tenant}.taleo.net/careersection/{section}/jobdetail.ftl?job={contestNo}&lang=en`
- **Board token:** tenant subdomain + career section code + portalNo (read "portalNo: '...'" from the jobsearch.ftl page; both tenants tested showed 101430233)
- **Own-domain sites:** Some employers front Taleo with their own career site; recognise links to *.taleo.net/careersection/{section}/jobdetail.ftl or jobsearch.ftl
- **robots.txt:** massanf.taleo.net/robots.txt and trinity.taleo.net/robots.txt return a 'Page not Found' HTML page (no robots rules)
- **Notes:** List item: jobId, contestNo, column[] -- column order is configured per career section (seen: [title, JSON-encoded locations array, posted date 'Nov 5, 2026']); locationsColumns gives the location column index. Employment type/salary only if the section shows them. Taleo Business Edition (tbe.taleo.net/chp0x/ats/careers/...) is a different product and was not tested.
- **Live boards seen:** Commonwealth of Massachusetts (MassCareers) (819 jobs), Trinity Industries (145 jobs)

### Teamtailor

- **Read via:** an RSS, Atom or XML job feed. Every Teamtailor career site serves a public JSON Feed (/jobs.json) and RSS (/jobs.rss) with full descriptions and an embedded schema.org JobPosting
- **List:** `GET https://{token}.teamtailor.com/jobs.json  (or /jobs.rss)`
- **Paging:** none observed; one document per site (16 and 12 items on tested sites); not verified on very large sites
- **Detail:** `https://{token}.teamtailor.com/jobs/{id}-{slug}`
- **Board token:** Subdomain of teamtailor.com, or the employer's custom career domain
- **Own-domain sites:** Many sites run on custom domains (careers.example.com). Recognise by images.teamtailor-cdn.com assets and the same /jobs, /jobs.json, /jobs.rss paths; robots.txt has 'Disallow: /jobs/internal/' and a Content-Signal line
- **robots.txt:** User-Agent: * / Disallow: /app/ /messages/ /messenger/ /facebook/tab/ /jobs/internal/ -- /jobs.json and /jobs.rss allowed. Also 'Content-Signal: search=yes, ai-train=no, ai-input=yes' (career.teamtailor.com) and 'Content-Signal: search=no, ai-train=no, ai-input=no' (polestar.teamtailor.com).
- **Blockers:** Per-site Content-Signal in robots.txt: some employers set search=no (Polestar). It is a usage reservation, not a crawl block; ERIO should decide whether to honour search=no (suggest skipping such sites).
- **Notes:** jobs.json items: id (uuid), title, url, date_published, content_html, _jobposting {identifier.value (numeric id), datePosted, employmentType, jobLocation[] addresses, hiringOrganization}. RSS adds remoteStatus (none/hybrid/fully), tt:locations, tt:department, tt:role. Salary not seen. Teamtailor's official API needs a key; the feeds do not.
- **Live boards seen:** Teamtailor (16 jobs), Polestar (12 jobs)

### Trakstar

- **Read via:** the platform's own JSON or XML interface. The legacy Recruiterbox widget API (jsapi.recruiterbox.com/v1/openings) still serves Trakstar Hire openings as public JSON with full descriptions
- **List:** `GET https://jsapi.recruiterbox.com/v1/openings?client_name={token}`
- **Paging:** offset/limit (meta {offset, limit 20, total}); pass &offset=N&limit=N
- **Detail:** `https://{token}.hire.trakstar.com/jobs/{id}/`
- **Board token:** Subdomain of hire.trakstar.com (e.g. rideco); same value as the Recruiterbox client_name
- **Own-domain sites:** Employers may embed the widget on their own site; recognise links to {x}.hire.trakstar.com or calls to jsapi.recruiterbox.com
- **robots.txt:** jsapi.recruiterbox.com: 'User-agent: *' 'Disallow: /prepare*' 'Allow: /'. rideco.hire.trakstar.com: 'User-agent: *' 'Disallow: /prepare*' 'Disallow: /published_jobs_list_v2*' 'Allow: /'
- **Notes:** Opening fields: id, title, client_name, description (HTML), location {city, state, country, zipcode}, tags, hosted_url, allows_remote, position_type ('full_time'), team, close_date. Hosted board https://{token}.hire.trakstar.com/ lists /jobs/{id}/ links (9 for RideCo, matching the API). Some boards say the employer left Trakstar (e.g. evergage); namati returned total 0.
- **Live boards seen:** RideCo (9 jobs), Registrar Corp (3 jobs)

### TriNet

- **Read via:** the job pages' HTML (no feed or structured data). Server-rendered HTML board and job pages with no JSON feed and no JSON-LD (.json/.xml/.rss suffixes all return HTML)
- **List:** `GET https://app.trinethire.com/companies/{token}/jobs`
- **Paging:** none seen; all jobs on one page (17 for Precor)
- **Detail:** `https://app.trinethire.com/companies/{token}/jobs/{jobId}-{slug}`
- **Board token:** {numericCompanyId}-{company-slug}, e.g. 31905-adaptation
- **Own-domain sites:** Not observed; links go to app.trinethire.com/companies/...
- **robots.txt:** Cloudflare-managed: 'User-agent: *' 'Content-Signal: search=yes,ai-train=no,use=reference' 'Allow: /'; AI training bots (GPTBot, ClaudeBot, CCBot, etc.) 'Disallow: /'
- **Blockers:** Behind Cloudflare, but plain curl with our UA got 200. No posted date on job pages.
- **Notes:** One detail request per job needed.
- **Live boards seen:** Adaptation (7 jobs), Precor, Incorporated (17 jobs)

### UltiPro

- **Read via:** the job pages' HTML (no feed or structured data). robots.txt disallows the full JSON search endpoint (.../JobBoardView/LoadSearchResults). The allowed board page embeds only up to 20 featured jobs as JSON, and the allowed detail pages embed the full job as JSON.
- **List:** `GET https://recruiting.ultipro.com/{tenantCode}/JobBoard/{boardGuid}/`
- **Paging:** None. The page script contains `initialFeaturedOpportunities: [...]` (a JSON array, at most 20 seen). The real list is POST {tenantCode}/JobBoard/{boardGuid}/JobBoardView/LoadSearchResults (pageSize 50), but robots.txt disallows */JobBoardView, so do not use it.
- **Detail:** `https://recruiting.ultipro.com/{tenantCode}/JobBoard/{boardGuid}/OpportunityDetail?opportunityId={opportunityGuid}`
- **Board token:** host (recruiting.ultipro.com or recruiting2.ultipro.com) + tenant code (e.g. COM1019CTDI1) + job board GUID
- **Own-domain sites:** Boards are hosted on recruiting.ultipro.com and recruiting2.ultipro.com; employers link to them or embed them in an iframe from their own career pages. Recognise them by URLs matching /{CODE}/JobBoard/{guid}. Legacy boards at rn22.ultipro.com/{CODE}/jobboard/listjobs.aspx also exist.
- **robots.txt:** recruiting.ultipro.com and recruiting2.ultipro.com: `User-agent: *` / `Disallow: /` / `Allow: */JobBoard/` / `Disallow: */JobBoardView` / `Disallow: */JobBoard/*/Styles` / `Disallow: */JobBoard/*/AnonymousSessionCheck`. Board pages and OpportunityDetail pages are allowed. The LoadSearchResults JSON API (under /JobBoardView/) is disallowed.
- **Blockers:** robots.txt disallows the search API, so only featured jobs (about 20 at most) can be found on each board. curl saw no bot challenge.
- **Notes:** A connector built this way would miss most jobs on large boards. Treat it as low priority, or index these employers through another source they also publish to. Remote/onsite comes from JobLocationType; full-time comes from the FullTime boolean.
- **Live boards seen:** CTDI (20 jobs), Regal (20 jobs)

### WeRecruit

- **Read via:** the job pages' HTML (no feed or structured data). Career pages on careers.werecruit.io are rendered on the server and list job links. Detail pages have the full text, but no JobPosting JSON-LD (only Organization) and no feed or public API.
- **List:** `GET https://careers.werecruit.io/{lang}/{company}`
- **Paging:** None seen: all offers are on one page. Job links match /{lang}/{company}/offres/{slug}-{hexId}. A global sitemap, https://careers.werecruit.io/sitemap.xml (3.5 MB, about 23k URLs), lists every company and offer URL across all tenants.
- **Detail:** `https://careers.werecruit.io/{lang}/{company}/offres/{slug}-{hexId}`
- **Board token:** company slug (e.g. gys, ge16-emploi) plus language prefix fr (en may also exist)
- **Own-domain sites:** Some clients may put their own domain in front of it. Recognise it by links to careers.werecruit.io, assets from wio.blob.core.windows.net, and the werecruit.com link with utm_medium=site_carriere_client. Apply e-mail addresses are at apply.werecruit.io.
- **robots.txt:** careers.werecruit.io: `User-agent: *` / `Allow: /` / `Sitemap: https://careers.werecruit.io/sitemap.xml`
- **Notes:** external_id is the hex suffix of the slug. The only date shown is the last-updated date, not the posting date. Skip 'candidature-spontanee' entries. The labels to parse are in French.
- **Live boards seen:** GYS (5 jobs), GE16 Emploi (12 jobs)

### Workable

- First-release connector; endpoint and limits are in [sources.md](sources.md).

### Workday

- **Read via:** the platform's own JSON or XML interface. Career sites call a public JSON search endpoint (CXS) that needs no auth, and the detail JSON has the full HTML description.
- **List:** `POST https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs`
- **Request body:** `{"limit":20,"offset":0,"appliedFacets":{},"searchText":""}`
- **Paging:** offset/limit, with limit at most 20. The response includes total, which stops at 2000 on very large sites; use facets to split those.
- **Detail:** `https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}`
- **Board token:** tenant + data-centre number (wd1, wd3, wd5, wd12, wd103 ...) + site name, taken from the URL https://{tenant}.wd{n}.myworkdayjobs.com/{site}
- **Own-domain sites:** Rare. Some employers embed or link to it from careers.example.com. Recognise it by myworkdayjobs.com links or /wday/cxs/ XHR requests.
- **robots.txt:** Set per tenant. nvidia.wd5: `User-agent: *` / `Allow: /NVIDIAExternalCareerSite/` / `Disallow: /talentcommunity/` / `Disallow: /refreshFacet/`, plus a few other sites. salesforce.wd12 is similar. No rule disallows /wday/cxs. Check each tenant, because some sites (e.g. NVIDIAExternalCareerSiteResearch) are disallowed.
- **Notes:** The list gives title, externalPath, locationsText ('5 Locations' when there are several), postedOn ('Posted Today' or 'Posted 30+ Days Ago') and bulletFields[0], which is the requisition ID. Use the detail startDate for posted_at. Salary is sometimes only in the description text. Each tenant has a sitemap at /{site}/siteMap.xml.
- **Live boards seen:** NVIDIA (2000 jobs), Salesforce (1546 jobs)

### Zoho Recruit

- **Read via:** the job pages' HTML (no feed or structured data). There is no public API (the OAuth API only covers your own organization). The careers page embeds all published jobs as a JSON array in a hidden input, so one GET per board is enough to parse them.
- **List:** `GET https://{subdomain}.zohorecruit.com/jobs/Careers`
- **Paging:** None. All jobs are in `<input type="hidden" id="jobs" value="[...HTML-escaped JSON...]">`
- **Detail:** `https://{subdomain}.zohorecruit.com/jobs/Careers/{id}/{slug}`
- **Board token:** subdomain on zohorecruit.com (or the regional zohorecruit.eu / .in / .com.au), or a custom domain
- **Own-domain sites:** Common (e.g. careers.zohocorp.com). Recognise them by the /jobs/Careers path, the hidden input with id="jobs", and the robots.txt header 'Zoho Corp. -- https://www.zoho.com/recruit'.
- **robots.txt:** Zoho Recruit hosts: `User-agent: *` / `Allow: /jobs` / `Allow: /jobs/` / `Allow: /jobs/*` / `Allow: /careers` / `Allow: /recruit/downloadrssfeed` / `Allow: /recruit/sitemapfeed` ... / `Disallow: /23`.
- **Blockers:** Pages are large (1.8 to 2.6 MB each).
- **Notes:** JSON keys: id, Posting_Title, Job_Opening_Name, City, State, Country (or Country1), Job_Type, Date_Opened (YYYY-MM-DD, not always present), Remote_Job, Industry, Work_Experience and Job_Description. The apply URL is the detail page. robots.txt allows /recruit/downloadrssfeed, but I did not verify that feed's URL format. zylker.zohorecruit.com is Zoho's demo tenant, so exclude it.
- **Live boards seen:** Accounting Baba (23 jobs), Zoho Corporation (2 jobs)

## Job-board platforms

### Niceboard

- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). robots.txt disallows the board's /api/ JSON. Every board has /sitemap-jobs.xml, and job pages carry full JobPosting JSON-LD.
- **List:** `GET https://{board-host}/sitemap-jobs.xml`
- **Paging:** None. One sitemap lists every job URL (/job/{numericId}-{slug}).
- **Detail:** `https://{board-host}/job/{id}-{slug}`
- **Board token:** board host: {board}.niceboard.co or the board's custom domain
- **Own-domain sites:** Most boards use custom domains (e.g. jobs.forcebrands.com). Recognise them by assets from cdn.niceboard.co or cdn2.niceboard.co, logos under cdn.niceboard.co/boards/{board}/, and the robots.txt pattern `Disallow: /api/` + `Crawl-delay: 1`.
- **robots.txt:** Both boards: `User-agent: *` / `Allow: /` / `Disallow: /api/` / `Crawl-delay: 1`
- **Blockers:** /api/jobs exists, but robots.txt disallows it, so do not use it. The 1-second crawl delay allows one detail request per second (829 jobs take about 14 minutes).
- **Notes:** The sitemap may include expired jobs, so check validThrough. Remote status is not stated unless jobLocationType is present. The /jobs path returns 404 on these boards; the home page is the listing.
- **Live boards seen:** United Way Job Bank (United Way of Greater Houston) (166 jobs), ForceBrands (829 jobs)

### WP Job Manager

- **Read via:** the platform's own JSON or XML interface. The WordPress REST API exposes the job_listing post type with full HTML content and meta (location, company, application, remote, salary). The built-in RSS job feed is a fallback.
- **List:** `GET https://{site}/wp-json/wp/v2/job-listings?per_page=100&page={n}`
- **Paging:** page/per_page (max 100), with X-WP-Total and X-WP-TotalPages headers
- **Detail:** `https://{site}/wp-json/wp/v2/job-listings/{id}`
- **Board token:** site base URL (the WordPress install root)
- **Own-domain sites:** Always on the site's own domain. Recognise it by /job/{slug}/ permalinks, assets under /wp-content/plugins/wp-job-manager/, a working /?feed=job_feed, or the REST route /wp/v2/job-listings.
- **robots.txt:** sportyjob.com: `User-agent: *` / `Disallow: /wp-admin/` plus WooCommerce paths, then a second `User-agent: *` / `Disallow:`. radioinsight.com: `Disallow: /wp-admin/`, `/wp-includes/`, `/trackback/`, `/wp-login.php` and so on. Neither disallows /wp-json/ or /?feed=. jobicy.com: no rule matches /?feed=job_feed (it disallows /feed$ and query parameters such as ?s= and ?p=). jobspresso.co reportedly blocks its feed with a query-string wildcard, so check each site.
- **Blockers:** Varies by site. Some sites turn off REST for job_listing or sit behind Cloudflare (jobicy's REST returns 403). hsepeople.com returned 0 jobs from both REST and the feed. Fall back to the feed or to JobPosting JSON-LD on /job/ pages.
- **Notes:** REST meta keys: _job_location, _company_name, _company_website, _application (URL or email), _remote_position, _job_salary, _job_salary_currency, _job_salary_unit, _filled, _featured, and _job_expires where exposed. Only status=publish is returned, so expired jobs are left out; filled jobs can still be published, so check _filled. Sites may add their own meta.
- **Live boards seen:** SportyJob (2299 jobs), RadioInsight (53 jobs), Jobicy (feed only) (200 jobs)

### JobKit

- **Read via:** the platform's own JSON or XML interface. Every JobKit board serves a public JSON list at /jobs.json with full Markdown descriptions; public jobs need no auth. /jobs.rss also exists.
- **List:** `GET https://{board-host}/jobs.json?page={n}`
- **Paging:** page, 30 per page according to the docs. A page past the last one returns 404.
- **Detail:** `https://{board-host}/jobs/{id}-{slug}.json`
- **Board token:** board host: {board}.jobkit.io or a custom domain
- **Own-domain sites:** Yes (e.g. jobs.rubyonrails.org). Recognise them by `<link rel="alternate" type="application/rss+xml" title="RSS" href=".../jobs.rss">`, a working /jobs.json with the keys arrangement, term and plan, and Rails ActiveStorage /files/representations/proxy/ URLs.
- **robots.txt:** jobs.rubyonrails.org and elixir.jobkit.io: robots.txt contains only the default Rails comment line, so nothing is disallowed.
- **Notes:** Keys: id, title, description (Markdown), location, arrangement (remote/hybrid/onsite), salary (can be free text, e.g. '160,000-200,000 + equity'), salary_currency, salary_period, company, company_website, application_type with application_url or application_email, term.name (Full-time...), category.name, url and created_at. I found only one JobKit board that has jobs; the platform is small.
- **Live boards seen:** Ruby on Rails official job board (13 jobs), Elixir job board (0 jobs)

### Jobboardly

- **Read via:** the platform's own JSON or XML interface. Boards serve a public /jobs.json that returns all jobs in one request (HTML and plain description, salary, apply link). /jobs.rss and JobPosting JSON-LD are also available.
- **List:** `GET https://{board-host}/jobs.json`
- **Paging:** None observed. One response returned all 336 jobs, and ?page=2 returned the same full list.
- **Detail:** `https://{board-host}/jobs/{slug}-{hexId}`
- **Board token:** board host (a custom domain, or {board}.jobboardly.com)
- **Own-domain sites:** Nearly all boards use custom domains. Recognise them by images on cdn.jobboardly.com, assets from assets.jobboardly.com, and the RSS link to /jobs.rss.
- **robots.txt:** medicalcourierjobs.com and apnejob.com: `User-agent: *` / `Allow: /` / `Sitemap: .../sitemap.xml`
- **Notes:** JSON keys: title, arrangement (contract/full-time...), location ('onsite' or 'remote', so it is the remote flag, not a place), location_limits (country codes), published_at, expires_at, application_link, description.html and description.plain, company.name, salary {schedule, minimum.cents, maximum.cents, currency_iso} and links.self. There is no id field, so use the hex suffix of links.self. City text is only in the RSS feed and the JSON-LD. coer.jobboardly.com (Missouri S&T) no longer exists and redirects to jobboardly.com. Responses can be large (about 5 MB).
- **Live boards seen:** Medical Courier Jobs (336 jobs), ApneJob (141 jobs)

### Jobiqo

- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). Boards are decoupled Drupal + Next.js (Apollo GraphQL, undocumented); no public feed found, but sitemap.xml lists every /job/ URL and each job page carries a full JobPosting JSON-LD
- **List:** `GET https://{board_host}/sitemap.xml`
- **Paging:** single urlset (Drupal simple_sitemap); filter <loc> containing '/job/'. /search/sitemap.xml holds only category/location search pages
- **Detail:** `https://{board_host}/job/{slug}-{numeric_id}`
- **Board token:** board hostname (e.g. jobs.aerosociety.com, www.miamijobs.com); the external ID is the numeric suffix of the job slug
- **Own-domain sites:** Always on the customer's own domain. How to spot one: the HTML includes __NEXT_DATA__ with __APOLLO_STATE__, the strings 'jobiqo' / 'JOBIQO_AIR_TRACKING_ACTIVE' / 'Jobiqo login', image paths under /sites/default/files/styles/..., the sitemap comment 'Generated by the Simple XML Sitemap Drupal module', robots.txt 'Disallow: /api/gmapi' plus a second Sitemap at /search/sitemap.xml, and Crawl-delay: 10 on some boards
- **robots.txt:** jobs.aerosociety.com: 'User-agent: * / Disallow: /api/gmapi' (everything else allowed). www.miamijobs.com: 'User-agent: * / Crawl-delay: 10 / Disallow: /api/gmapi'. www.nursingtimesjobs.com (older Drupal Jobiqo): 'Crawl-delay: 10', Drupal defaults, 'Disallow: /search/'
- **Blockers:** www.nursingtimesjobs.com (an older Jobiqo board) serves a JavaScript 'Bot Check' page to non-browser clients on job pages, so it cannot be read. Honour Crawl-delay: 10 where set.
- **Notes:** The JobPosting.description is HTML-entity-escaped (&lt;p&gt;...), and on miamijobs it is escaped twice, so unescape it until it stops changing. The listing page /jobs is server-rendered with 10 jobs and a totalCount in __APOLLO_STATE__ (a possible fallback). There is no RSS on the new stack. A vendor GraphQL endpoint probably exists, but it is undocumented, so I did not probe it.
- **Live boards seen:** RAeS Aerospace Jobs (Royal Aeronautical Society) (300 jobs), MiamiJobs.com (TheJobNetwork) (31 jobs)

### JBoard.io

- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). Built-in RSS /rss/jobs exists but every board's robots.txt disallows /rss/; the API needs a key; sitemap-jobs-N.xml plus JobPosting JSON-LD on job pages are allowed and complete
- **List:** `GET https://{board_host}/sitemap-jobs-{n}.xml`
- **Paging:** sitemap index at /sitemap.xml lists sitemap-jobs-1.xml, -2 ...
- **Detail:** `https://{board_host}/jobs/{numeric_id}-{slug}`
- **Board token:** board hostname ({name}.jboard.io or a custom domain); the external ID is the numeric prefix of the job slug (also in JSON-LD identifier.value)
- **Own-domain sites:** Most showcase boards use custom domains. How to spot one: robots.txt is exactly 'Disallow: /rss/ + Crawl-delay: 1 + Sitemap'; the footer says 'Powered by JBoard' (utm_source=powered_by_link); HTML has window.$JBoardAPI, main_api_url 'https://app.jboard.io/api', and assets from jboard-tenant.s3.us-west-1.amazonaws.com / d3535lqr6sqxto.cloudfront.net; sitemap names are sitemap-jobs-N.xml
- **robots.txt:** nuclearjobscanada.ca, jobs.vpppa.org, demo.jboard.io: 'User-agent: * / Disallow: /rss/ / Crawl-delay: 1 / Sitemap: https://{host}/sitemap.xml'. /jobs/ and the sitemaps are allowed; the RSS is not.
- **Blockers:** RSS is disallowed by robots.txt. The public API (app.jboard.io/api) needs an API key. The sitemap has no lastmod and may include expired jobs, so check validThrough.
- **Notes:** I fetched demo.jboard.io/rss/jobs once before reading robots.txt (an RSS 2.0 feed of the latest 100 jobs with company, location, pubDate and tags). Do not use it in the connector. JSON-LD verified on jobs.vpppa.org/jobs/165334564-safety-specialist.
- **Live boards seen:** Nuclear Jobs Canada (CNA) (929 jobs), VPPPA Job Board (730 jobs)

### JobBoardFire

- **Note:** Only one live board found (a second platform board had no jobs)
- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). Nuxt SPA backed by an undocumented private API (jobboardfire.com/api/). No feed found; sitemap-jobs.xml plus JobPosting JSON-LD on /j/{slug} pages work
- **List:** `GET https://{board_host}/sitemap-jobs.xml`
- **Paging:** single file; sitemap index at /sitemap.xml (sitemap-pages, -jobs, -companies, -removals)
- **Detail:** `https://{board_host}/j/{slug}-{12 hex}`
- **Board token:** board hostname ({name}.jobboardfire.com or a custom domain); JSON-LD identifier.value is a UUID
- **Own-domain sites:** Yes (e.g. jobs.girlboss.com). How to spot one: robots.txt is exactly 'User-agent: * / Disallow: /*?*&*&*' plus Sitemap; window.__NUXT__.config has SYSTEM_HOSTNAME:'jobboardfire.com' and BROWSER_BASE_URL:'https://jobboardfire.com/api/'; assets come from d3pgq7fhdc5jrl.cloudfront.net and jobboardfire.twic.pics; there is a displayJobBoardFireBranding flag; job URLs look like /j/{slug}-{hash}; the sitemap has a sitemap-removals.xml
- **robots.txt:** 'User-agent: * / Disallow: /*?*&*&*' on jobs.girlboss.com, demo and pharmajoblinks; jobboardfire.com: 'User-agent: * / Allow: /'
- **Blockers:** Cloudflare: after about 10 quick requests to different *.jobboardfire.com subdomains, I got HTTP 429 'Just a moment...' challenges (stpetetechjobs). Keep the rate low. Many *.jobboardfire.com subdomains in CT logs are expired trials (pharmajoblinks shows an 'expired' notice; 14 probed had no jobs sitemap). Product Marketing Alliance, the vendor's case study, has moved off the platform (alliance-jobs.vercel.app, robots Disallow: /).
- **Notes:** The JSON-LD inside <script type=application/ld+json> is HTML-entity-encoded (&quot;), so html.unescape it before json.loads. Many listings on girlboss are aggregated backfill (Greenhouse/Workday/SmartRecruiters links), so expect duplicates with the ATS connectors. I verified only ONE live board with jobs; I could not verify a second.
- **Live boards seen:** Girlboss Jobs (401 jobs), JobBoardFire demo (no jobs) (0 jobs)

### SmartJobBoard

- **Read via:** an RSS, Atom or XML job feed. Every board publishes RSS at /rss/ (advertised by <link rel=alternate>) with FULL HTML descriptions for the latest 50 jobs; the sitemap plus JSON-LD fills in the rest
- **List:** `GET https://{board_host}/rss/`
- **Paging:** none: latest 50 items only. For the full set, read /sitemap.xml (single urlset; filter <loc> containing '/job/') and the JSON-LD on each job page
- **Detail:** `https://{board_host}/job/{numeric_id}/{slug}/`
- **Board token:** board hostname (custom domain or {name}.mysmartjobboard.com, the hosted subdomain I did not verify); the external ID is the numeric ID in /job/{id}/
- **Own-domain sites:** Usually custom domains. How to spot one: the RSS <generator>Smart Job Board</generator>; HTML loads assets from *.smartjobboard.com/{version}/templates/(BreezeDND/BootstrapDND)/ and calls smartjobboard.com/autocomplete/; the footer says 'SmartJobBoard Job Board Software'; robots.txt has Disallow /files/files/, /download/, /application-redirect/ and a bingbot block with 'Disallow: /jobs/?'
- **robots.txt:** Both: 'User-agent: * / Disallow: /files/files/ / Disallow: /download/ / Disallow: /application-redirect/ / Sitemap: .../sitemap.xml'. /rss/ and /job/ are allowed. (bingbot alone also has 'Disallow: /jobs/?'.) psychologicalscience sitemap: 73 /job/ URLs
- **Blockers:** None seen. The admin-configured 'Standard XML feed' (all jobs, all fields) has a URL that is not public or discoverable, and the API is Enterprise-only and needs a key.
- **Notes:** Each RSS item description starts with plain-text location and company lines, followed by the HTML description. Use JSON-LD for structured location.
- **Live boards seen:** Association for Psychological Science (50 jobs), Academic Careers (50 jobs)

### JobBoard.io

- **Read via:** an RSS, Atom or XML job feed. Every board serves RSS 2.0 at /jobs.rss (linked via rel=alternate) covering all active jobs; descriptions are truncated, so take full descriptions from the JobPosting JSON-LD on job pages
- **List:** `GET https://{board_host}/jobs.rss`
- **Paging:** none observed (?page=2 returns the same 19 items); appears to hold all active jobs (19 RSS items vs 20 sitemap URLs on cityandstateny). Full list also in /sitemaps/jobs/job_sitemap_details.xml?finish_id=..&start_id=.. (linked from /sitemap.xml)
- **Detail:** `https://{board_host}/jobs/{numeric_id}-{slug}`
- **Board token:** board hostname ({name}.jobboard.io or a custom domain); the external ID is the numeric prefix of the slug
- **Own-domain sites:** Usually custom domains. How to spot one: robots.txt contains 'Disallow: /backfills/latest_jobs', '/clk/*', '/jobs/*/tracker' and '/employers/*'; logos under /uploads/job/logo/{id}/; the RSS <generator> is the site name and the title is 'Latest jobs from {site}'; sitemap URLs are /sitemaps/jobs/job_sitemap_details.xml; HTML mentions jobboard.io
- **robots.txt:** Both hosts: 'User-Agent: * / Disallow: /jobs/*/tracker, /jobs/*/preview, /jobs/*/applicants, /jobs/*/manage, /messages/*, /applicants/new, /backfills/latest_jobs, /auth/*, /clk/*, /employers/*, /cdn-cgi/*'. /jobs.rss and /jobs/{id}-{slug} are allowed
- **Blockers:** The REST API (/api/v1/jobs/search) needs an X-Api-Key, so do not use it. /jobs.json and /jobs.xml return 404.
- **Notes:** The RSS title embeds company and location, so parse them or use JSON-LD. Admins can disable JobPosting markup per employer or feed (vendor docs), so some job pages may lack JSON-LD. Boards can use backfill (Indeed/ZipRecruiter), so expect duplicates.
- **Live boards seen:** City & State New York Jobs (19 jobs), Motionographer Jobs (1 jobs)

### Wiley Madgex

- **Read via:** an RSS, Atom or XML job feed. Madgex boards expose a paginated RSS search feed /jobsrss/ (linked via rel=alternate, with opensearch:totalResults); JobPosting JSON-LD on job pages supplies full descriptions
- **List:** `GET https://{board_host}/jobsrss/?Page={n}`
- **Paging:** 20 items per page, Page=1..ceil(totalResults/20) (Page=2 verified); opensearch:totalResults in the channel. Accepts the same filters as /jobs/ search (e.g. countrycode=US). Sitemap index at /sitemapindex.xml
- **Detail:** `https://{board_host}/job/{numeric_id}/{slug}/`
- **Board token:** board hostname (custom domain); the external ID is the numeric ID in /job/{id}/
- **Own-domain sites:** Always the publisher's domain (jobs.{publisher}.com). How to spot one: the HTML contains 'Madgex Job Board Platform', 'Madgex Tracking', and madgex-ds / mds-combobox assets; robots.txt has 'Disallow: /invalid-request/', '/analytics/', '*/emailjob/*', '*/previewjob/*' and 'Sitemap: /sitemapindex.xml'; RSS links carry ?TrackID=..&utm_source=rss
- **robots.txt:** Both: 'User-agent: * / Disallow: /invalid-request/ / Disallow: /analytics/ / Disallow: */emailjob/* / Disallow: */previewjob/* / Sitemap: .../sitemapindex.xml' (sciencecareers also has /apply-profile/). /jobsrss/ and /job/ are allowed
- **Blockers:** jobs.theguardian.com returns HTTP 403 ('Madgex Insights' error page) to our User-Agent, even for robots.txt, so some Madgex boards block non-browser clients. The Madgex Web Services API is partner-only and needs credentials. jobs.newscientist.com has closed.
- **Notes:** Strip the TrackID/utm params from links to get a stable job URL. With roughly 1,450 pages for large boards like Chronicle, crawl incrementally (newest first, stop at known IDs) with a 1-second delay. The JSON-LD employmentType is a stringified array on sciencecareers.
- **Live boards seen:** Science Careers (AAAS) (548 jobs), The Chronicle of Higher Education Jobs (29052 jobs)

### Talenetic

- **Blocked:** hosted boards disallow everything in robots.txt and require sign-in
- **Read via:** blocked: ERIO does not crawl it (see the reason). Could not find an open live board: the only verified Talenetic-hosted board disallows all crawling and redirects to a login page; known customer domains have lapsed
- **List:** `GET unknown`
- **Paging:** unknown
- **Detail:** `unknown`
- **Board token:** board hostname ({name}.talenetic.com or a custom domain)
- **Own-domain sites:** Footer 'Powered by: Talenetic Job Board Software'; hosted pattern {name}.talenetic.com; the home page may redirect to /Home/LoginTemp; favicon at /Images/Default/favicon.ico
- **robots.txt:** procontractjobs.talenetic.com: 'User-agent: * / Disallow: /' (whole site disallowed)
- **Blockers:** robots.txt Disallow: / on the hosted board, and the home page redirects to /Home/LoginTemp (login wall). britishmedicaljobs.com now redirects to an unrelated casino site. The vendor site lists no customer boards, and crt.sh lookups for *.talenetic.com failed (502/404). Third-party sites mention RSS/XML job feeds, but I could not verify any.
- **Notes:** UNVERIFIED: I found no live, crawlable Talenetic board. Revisit if a specific customer domain turns up, and check its robots.txt and rel=alternate RSS.
- **Live boards seen:** Pro-Contract Jobs (None jobs), BritishMedicalJobs.com (former customer, domain lapsed) (None jobs)

### JobMount

- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). Boards have an RSS feed at /main/rss/feed (explicitly allowed in robots), but it is capped at 100 items and contains unrendered template junk; the sitemap lists every /career/ job URL, and job pages carry clean JobPosting JSON-LD
- **List:** `GET https://{board_host}/sitemap.xml`
- **Paging:** single urlset; filter <loc> containing '/career/'. For incremental updates use GET https://{board_host}/main/rss/feed (latest 100, no pagination)
- **Detail:** `https://{board_host}/career/{numeric_id}/{slug}`
- **Board token:** board hostname (custom domain); the external ID is the numeric ID in /career/{id}/
- **Own-domain sites:** Always the customer's own domain. How to spot one: the footer says 'Powered by JobMount Job Board Software' and links to jobboardmount.com; robots.txt has 'Allow: /main/rss/feed', 'Allow: /main/download', 'Disallow: /main', '/candidate/job_apply', '/employer/private' and '/imglib_thumbnails'; job URLs look like /career/{id}/{slug}; RSS items carry <city>/<state>/<country> tags
- **robots.txt:** fleetjobs/wacities/remotefetch: 'User-agent: * ... Allow: /main/rss/feed / Allow: /main/download / Allow: /main/clients/products / Disallow: /main / Disallow: /admin / Disallow: /candidate/job_apply ...'; 'Disallow: /' only for Googlebot-Image and Jooble. /career/ is allowed
- **Blockers:** The vendor site www.jobboardmount.com returns HTTP 403 (AWS ELB) to our User-Agent, but customer boards respond normally. The XML/JSON export feed is a paid Premium option and is not public.
- **Notes:** RSS descriptions contain unrendered Velocity placeholders ($companies.get(...), $salary, $map.get("vacancy_industry")), and pubDate is MM/DD/YYYY rather than RFC-822, so parse defensively. The sitemap probably includes expired jobs, so check validThrough. Former customers diversityjobs.com and aghires.com have moved to WordPress/HubSpot.
- **Live boards seen:** FleetJobs.com (4231 jobs), AWC JobNet (Association of Washington Cities) (100 jobs), RemoteFetch (100 jobs)

### CareerSiteCloud

- **Note:** Only wpp.careersitecloud.com allows crawlers; other tenants found disallow everything
- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). Each hosted career site publishes a sitemap.xml of all job URLs and every job page carries full schema.org JobPosting JSON-LD; no public JSON/RSS feed was found
- **List:** `GET https://{site}.careersitecloud.com/sitemap.xml`
- **Paging:** none; one sitemap lists every job (wpp: 2255 URLs, 2163 of them /job-*)
- **Detail:** `https://{site}.careersitecloud.com/job-{24-hex-id}-{slug}`
- **Board token:** Subdomain of careersitecloud.com (e.g. wpp, mn-dps, bca); job id is a 24-hex ObjectId in the URL
- **Own-domain sites:** Vendor (Aspen Technology Labs, also makes JobMount) advertises sites on clients' own domains and iframe embeds. Recognise by assets from atl-csc.s3.amazonaws.com and cloudfront.careersitecloud.com, job URLs /job-{24hex}-{slug}, search forms posting to /module-...?module=search_job, and 'careersitecloud' strings in the HTML
- **robots.txt:** Per site. wpp: 'User-agent: * / Allow: / / Disallow: /log-view-*' (jobs allowed). mn-dps and bca: 'User-agent: * / Disallow: / ' (whole site disallowed, so skip those). www.careersitecloud.com returns 403 even for robots.txt
- **Blockers:** AWS load balancer returns 403 to non-browser clients on www.careersitecloud.com and on deactivated tenant subdomains (mpca, loyola-school, leo-pharma, prototypes); active tenants return 200. Some tenants disallow all crawling in robots.txt
- **Notes:** Often an aggregation layer (the WPP site pulls from its agencies' ATSs), so jobs may duplicate postings already indexed elsewhere; dedupe on apply URL. No salary or remote flag in the JSON-LD sample.
- **Live boards seen:** WPP (WPP Media and agencies) (2163 jobs), Minnesota Dept of Public Safety (11 jobs), Minnesota Bureau of Criminal Apprehension (2 jobs)

### JobBoard.com

- **Note:** Only one live board found
- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). Boards expose /sitemap.xml -> /xml-sitemaps/1.xml with job URLs and job pages carry rich JobPosting JSON-LD including salary; the platform's own /_feeds/ path is disallowed
- **List:** `GET https://{board-domain}/sitemap.xml (index) -> https://{board-domain}/xml-sitemaps/1.xml`
- **Paging:** sitemap index with numbered /xml-sitemaps/{n}.xml (only 1.xml worked on gradsouthwest; 2 and 3 returned 500)
- **Detail:** `https://{board-domain}/jobs/{slug}/{jobId}-{n}/`
- **Board token:** Board's own domain; job id like 3867-1 in URL (identifier.value 00003867-1)
- **Own-domain sites:** All boards run on customers' domains. Recognise by hosting IP 168.63.98.176 (Azure, same as www.jobboard.com), asset paths /_resx/ and /_cachebusted/_resx/templates/, /_resx/imageresourcegooglejobs/ logos, and the shared robots.txt (Disallow /_feeds/, /vacancyclickincrementer.ashx, Crawl-delay 0.2, ClaudeBot blocked)
- **robots.txt:** 'User-agent: * / Disallow: /_feeds/ / Disallow: /_integrations/ / Crawl-delay: 0.2 / Sitemap: https://{domain}/sitemap.xml'. /jobs/ and /xml-sitemaps/ allowed. Separate groups disallow ClaudeBot, Claude-Web, MJ12bot, Bytespider entirely
- **Blockers:** Built-in /_feeds/ is disallowed. robots.txt explicitly disallows ClaudeBot/Claude-Web, which matters if ERIO identifies as such (ERIO's own UA is not listed). Only one live board verified; other 'our work' clients (formwork-jobs.com, orkneyemployment.co.uk, motortrader jobs, architects-online.co.uk) no longer run it; jobfiliate.io (testimonial client) does not respond
- **Notes:** Second live board NOT verified. HotLizard sister product RecruiterSites (same IP) likely shares the sitemap/JSON-LD layout. Do not confuse with JobBoard.io (ZipRecruiter-powered).
- **Live boards seen:** Grad South West (graduate job board) (7 jobs)

### Artha

- **Read via:** blocked: ERIO does not crawl it (see the reason). Sitemaps list every job URL, but /job-detail/ pages answer a Cloudflare 'Just a moment...' challenge (403) to non-browser clients and the list pages render client-side from a non-public API
- **List:** `GET https://{board-domain}/sitemap.xml -> https://{board-domain}/jd/{n}/sitemap.xml`
- **Paging:** numbered /jd/{n}/sitemap.xml
- **Detail:** `https://{board-domain}/job-detail/{slug} (Cloudflare challenge, 403)`
- **Board token:** Board domain, or {slug}.arthajobboard.com hosted subdomain (e.g. fpnajobs.arthajobboard.com)
- **Own-domain sites:** Most boards use their own domains. Recognise by assets from cdn-static.arthajobboard.com (Next.js under /static-assets/_next/), '{slug}.arthajobboard.com' references, and sitemap layout /main/, /jd/{n}/, /company-detail/{n}/
- **robots.txt:** fpnajobs.com and edujobsindia.com: 'User-agent: * / Allow: /' plus Sitemap line, so crawling is permitted but Cloudflare challenges detail pages
- **Blockers:** Cloudflare bot challenge on /job-detail/ for curl; home and /browse-jobs return 200 but hold no job data (client-rendered). GetApp states Artha has no public API
- **Notes:** Sitemap counts may include expired jobs. Revisit if Artha exposes a feed; do not work around the challenge.
- **Live boards seen:** FP&A Jobs (FP&A Professionals Institute) (2342 jobs), EduJobsIndia (13120 jobs)

### jobboardsoftware.com

- **Read via:** the platform's own JSON or XML interface. jobboardsoftware.com now redirects to exenzo.com; Exenzo boards call an unauthenticated public JSON API that returns full jobs with descriptions, salary and apply URLs
- **List:** `GET https://{board}.api.exenzo.com/api/public/v1/job-boards/{jobBoardId}/jobs?page={n}&limit={k} (some boards have their own API host, e.g. https://api.vacatures.co/api/public/v1/job-boards/1/jobs)`
- **Paging:** page/limit; response {total, data[], aggregations, lastPage, currentPage}; default 10 per page, limit=50 accepted, per_page ignored
- **Detail:** `job_url field: https://{api-host}/api/public/v1/jobs/{uuid}/url (redirects to board page https://{board-domain}/vacature/{slug})`
- **Board token:** API base host plus job-board id; both appear in the page's window.__NUXT__ state: baseApiUrl and job_boards[0].id (1 on both boards tested)
- **Own-domain sites:** All boards on own domains (Nuxt SPA). Recognise by window.__NUXT__ with baseApiUrl on *.api.exenzo.com, images at storage.googleapis.com/exenzo-jobboard/{slug}/, job URLs /vacature/{slug}
- **robots.txt:** greenjobs.api.exenzo.com and api.vacatures.co: 'User-agent: * / Disallow:' (everything allowed). greenjobs.nl and vacatures.co have no robots.txt (404)
- **Notes:** Dutch market. vacatures.co total=5000 looks like a search cap; filter by segment/date for more. Old jobboardsoftware.com customers: greenjobs.nl, carriere.nu, hirehr.nl, vacatures.co, jobboost.io, navingocareer.com (now 410). An Indeed XML feed per board is advertised but its URL was not found.
- **Live boards seen:** Greenjobs.nl (267 jobs), Vacatures.co (5000 jobs)

### jobBoardHQ

- **Read via:** the job pages' HTML (no feed or structured data). Job pages carry JobPosting JSON-LD but there is no sitemap, the advertised atom.xml serves HTML, and the /search list is ASP.NET WebForms with postback paging, so listing needs page parsing
- **List:** `GET https://{board-domain}/search (first 20 jobs; more need __doPostBack form posts, ddlPageRows control)`
- **Paging:** ASP.NET postback only; ?page=N ignored; site caps results at the top 500 jobs
- **Detail:** `https://{board-domain}/job/{6-char-key}/{title-slug}/{city}/{state} (JSON-LD JobPosting)`
- **Board token:** Board's own domain; job key is 6 lowercase alphanumerics (JSON-LD identifier jobKey)
- **Own-domain sites:** All boards on own domains. Recognise by 'Powered by' footer logo alt=JobBoardHQ, assets on siteresource.blob.core.windows.net/assets/prod/{code}/, <link rel=alternate type=application/atom+xml href=/atom.xml>, ASP.NET ctl00$MainContent$lvJob controls
- **robots.txt:** robots.txt is empty (200, no rules) on both boards, so everything is allowed; no Sitemap line and /sitemap.xml returns the HTML home page
- **Blockers:** No machine-readable list: atom.xml is advertised but returns HTML. Job-list API exists only on the Enterprise plan with a key (per fantastic.jobs)
- **Notes:** Job counts are the 20 jobs on the first /search page, not board totals (greaterroccareers shows the 'top 500 jobs' limit message). Other customers on jobboardhq.com: jobs.macslist.org, njschooljobs.com, estatejobs.com, roaddogjobs.com.
- **Live boards seen:** JobsInDoorCounty.com (20 jobs), GreaterROCCareers (Rochester NY) (20 jobs)

### Nodex

- **Note:** Only one live board found
- **Read via:** schema.org JobPosting data on each job page (found through a sitemap or listing page). Nodex boards (internal name fabricjobs) list every job in /sitemap.xml and job pages have JobPosting JSON-LD; their /api/v1 is an authenticated posting API, not a public listing feed
- **List:** `GET https://{board-domain}/sitemap.xml`
- **Paging:** none; single sitemap (120 /job/ URLs on mytraveljobs, matching '120 jobs' on /find-jobs). HTML alternative: /modules/fabricjobs/lists/search/jobs?match=broad&sort=date&page={n} (10 per page)
- **Detail:** `https://{board-domain}/job/{slug}`
- **Board token:** Board's own domain; job identified by slug
- **Own-domain sites:** All boards on own domains. Recognise by footer 'Job board software by Nodex' linking to nodex.co.uk/services/job-board-software?referer={domain}, '(c) Nodex Limited', paths /modules/fabricjobs/, CSS classes fabricjobs-*, and a /api/v1/documentation page
- **robots.txt:** mytraveljobs.co.uk: 'Disallow: /find-jobs?*', 'Disallow: /jobs/*?*', 'Disallow: /sector/*?*' (listed before any User-agent line), then 'User-agent: PetalBot'. /job/{slug} and /sitemap.xml not disallowed
- **Blockers:** API (POST /api/v1/jobs/add etc.) needs credentials and is for employers posting, not reading
- **Notes:** Second live board NOT verified: portfolio boards Hungry Jobs, Recruiters Jobs, Security Vacancies no longer run Nodex or do not resolve; datatalentjobs.co.uk does not respond. BuiltWith claims about 49 live Nodex sites, mostly recruitment-agency sites.
- **Live boards seen:** My Travel Jobs (120 jobs)

### eJobBoard

- **Read via:** blocked: ERIO does not crawl it (see the reason). Vendor appears defunct: ejobboard.co.uk no longer resolves, ejobboard.com is a parked domain, and no live board running it was found
- **Board token:** unknown
- **Own-domain sites:** Was a WordPress-marketed hosted product (archived Feb 2025 page) advertising Indeed, Jobg8, Jobrapido, Adzuna and Broadbean integrations; client logos (GoGlobal, Live-in Care Friends, Diversity Link, Flexible Works) gave no verifiable live boards
- **robots.txt:** n/a (host does not resolve)
- **Blockers:** No live vendor site or boards found; nothing could be verified
- **Notes:** Not verified. Directories (jobboard.software, Cavuno) still list it at $49/mo + $100 setup. Do not confuse with eJobsiteSoftware.

### ejobsitesoftware.com

- **Read via:** an RSS, Atom or XML job feed. Self-hosted PHP job sites ship per-industry RSS 2.0 feeds (/rss/{industryId}.xml, indexed at /industry_rss.php) with title, link, full description and location; job pages also carry JobPosting JSON-LD
- **List:** `GET https://{board-domain}/industry_rss.php (index) -> https://{board-domain}/rss/{industryId}.xml`
- **Paging:** none; one feed per industry, union and dedupe on guid (13 feeds on eyetasticjobs, 257 on connectagri)
- **Detail:** `https://{board-domain}/{jobId}/{Title-City-ST}.html (JobPosting JSON-LD)`
- **Board token:** Board's own domain; numeric job id is the first path segment
- **Own-domain sites:** Installed on customers' own domains. Recognise by /industry_rss.php, /job_search.php (POST form), apply_now.php?query_string=..., job URLs /{id}/{Title}.html, a long boilerplate robots.txt (Disallow /classinc/, /tep/, /my_admin/, phpbb_login.php, tld.txt), and a stale sitemap.xml pointing at ejobsitesoftware.com/jobsite_demo/
- **robots.txt:** eyetasticjobs.com and connectagri.com: 'User-agent: *' with Disallows only for /_private/, /ads/, /apply_resume/, /my_admin/, /modules/, /resume/ etc.; /rss/, /industry_rss.php and job pages allowed. jobqlick.com puts 'User-agent: *' in the same group as 'User-agent: Amazonbot / Disallow: /', so treat it as disallowed
- **Blockers:** RSS items have no pubDate; the search list is a POST form. Some installs block crawlers in robots.txt (jobqlick)
- **Notes:** Counts: eyetastic = unique guids across its 13 feeds; connectagri = unique job links on its home page (its feeds were not fully enumerated). Other customers on the vendor home page: beveiligingsvacature.nl, recruitclever.co.uk, gurushrconsultancy.com.
- **Live boards seen:** Eyetastic Jobs (72 jobs), ConnectAgri (8 jobs)

