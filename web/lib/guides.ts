// Guides written for ERIO. Each says only what the site and its pipeline do
// today; when behaviour changes, change the guide with it. Pure data: the
// unit tests check that every link points at a page that exists.

export type GuideLink = { label: string; href: string };

export type GuideSection = {
  heading: string;
  paragraphs: string[];
  list?: string[];
};

export type Guide = {
  slug: string;
  title: string;
  description: string;
  sections: GuideSection[];
  /** Real pages to continue on. */
  links: GuideLink[];
};

export const GUIDES: Guide[] = [
  {
    slug: "search-well",
    title: "How to search well on ERIO",
    description: "Filters, wording and sorting that get you to the right jobs, and what the counts mean.",
    sections: [
      {
        heading: "Start with where, then narrow",
        paragraphs: [
          "Pick one or more countries first. A country filter shows roles based there and remote roles that accept applicants from there, and by default also remote roles open to anyone in the world. Switch worldwide-remote off when you only want jobs tied to a place.",
          "The number beside each filter value is how many jobs you would get by choosing it with your other choices kept. It changes as you filter, which is how you can tell quickly that a field has almost nothing in a country before you click.",
        ],
      },
      {
        heading: "Words that work",
        paragraphs: [
          "The search looks in the title, the employer's name, the place and the description, and wants every word you type to appear. Two or three words usually beat a long phrase. Use the plain job title (\"electrician\", \"data analyst\") and add the city in the location filter or the country picker rather than in the words.",
        ],
        list: [
          "Employers use different titles for the same work, so try a second wording before concluding there is nothing.",
          "Role categories (Engineering, Healthcare, Logistics and the rest) group titles for you; use them when you do not know the title.",
          "Sort by most recent to see what was posted lately, or by salary to see the highest stated pay first.",
        ],
      },
      {
        heading: "Pay and freshness",
        paragraphs: [
          "The Pay stated option keeps jobs whose employer gave a pay range, and the salary choices keep jobs at or above an amount in US dollars. The dollar figure is only for comparing jobs in one list; each job shows its pay in the currency and period the employer wrote. Many postings give no pay, so a pay filter hides them.",
          "Cards say New today for jobs posted in the last day and Checked 3h ago for how long since ERIO last confirmed the job on its employer's page.",
        ],
      },
      {
        heading: "Searches refresh themselves",
        paragraphs: [
          "When you search, ERIO answers from its index at once and also re-reads the employer boards behind your results, so new postings can appear within seconds. It is limited on purpose, so it stays a polite visitor to those sites.",
        ],
      },
    ],
    links: [
      { label: "Open the search", href: "/search" },
      { label: "Software engineer jobs", href: "/jobs/role/software-engineer" },
      { label: "Jobs that state pay", href: "/search?salary=1&sort=salary" },
    ],
  },
  {
    slug: "find-remote-work",
    title: "Finding remote work that you can actually take",
    description: "How remote scope works on ERIO, and how to tell a remote job open to you from one that is not.",
    sections: [
      {
        heading: "Remote does not mean everywhere",
        paragraphs: [
          "Many remote postings are open only to certain countries, because of tax, payroll or time zones. ERIO records this as the remote scope: a country, a region, or worldwide. A job page lists the countries a remote role accepts under Open to.",
          "On search, choose your country and leave worldwide-remote on. You then see local jobs, remote jobs that accept your country, and jobs open to anyone. Cards for remote roles that accept your country are marked Open to you.",
        ],
      },
      {
        heading: "Read the line, not the badge",
        paragraphs: [
          "A Remote badge tells you the work mode. Before applying, check Open to on the job page, then read the employer's own text for anything ERIO could not capture, such as a time-zone overlap or a requirement to live near an office a few days a month.",
        ],
      },
      {
        heading: "Good places to start",
        paragraphs: [
          "The market pulse shows how many open roles are remote overall. Each country's page and each role explorer page also shows its remote share, so you can see which fields offer the most remote work for you.",
        ],
      },
    ],
    links: [
      { label: "Remote jobs in search", href: "/search?type=remote" },
      { label: "Market pulse", href: "/pulse" },
      { label: "Role explorer", href: "/paths" },
      { label: "Engineering roles", href: "/paths/engineering" },
    ],
  },
  {
    slug: "follow-a-search-with-a-feed-reader",
    title: "Following a search with a feed reader",
    description: "Get new jobs for any search in your feed reader, with no account and no email.",
    sections: [
      {
        heading: "What you get",
        paragraphs: [
          "Every search can be followed as an Atom feed. A feed reader checks it for you and shows new jobs as they are added, newest first. Nothing is sent to your inbox and you do not sign in anywhere.",
        ],
      },
      {
        heading: "How to follow one",
        paragraphs: [
          "Run the search you care about, choose Follow this search, and copy the address into your feed reader's add-feed box. The address is the feed address with your filters in it, so you can also edit them by hand: q for words, country for country codes, role for a role category, type for remote, hybrid or onsite, and salary for a minimum or 1 for pay stated.",
          "The What's new page has feeds for the jobs posted in the last day, which suit a daily check.",
        ],
        list: [
          "Each entry links to the job's page on ERIO, where the Apply button leads to the employer.",
          "A feed holds the latest 50 matches. Follow a narrow search so that nothing falls off between checks.",
          "Readers ask the address again and again, so prefer a reader that checks a few times a day, not every minute.",
        ],
      },
      {
        heading: "Limits",
        paragraphs: [
          "A feed shows jobs that match now, so a job that is closed disappears from it. The feed is for people; if you need all the data, use the API, which has its own limits and documentation.",
        ],
      },
    ],
    links: [
      { label: "What's new today", href: "/new" },
      { label: "Search and follow", href: "/search" },
      { label: "The API", href: "/api" },
    ],
  },
  {
    slug: "read-a-jobs-freshness-and-sources",
    title: "Reading a job's freshness and sources",
    description: "What posted, checked, verified and the sources table on a job page tell you.",
    sections: [
      {
        heading: "Posted and checked are different",
        paragraphs: [
          "Posted is the date the employer gave. Checked is when ERIO last saw the job still listed on the employer's page. A job posted two months ago and checked an hour ago is old but live; a job posted yesterday and not checked for days deserves a second look.",
          "Some employers give no posted date. Those jobs show recently, and ERIO counts them from the day it first saw them.",
        ],
      },
      {
        heading: "Verified open, and when it is not",
        paragraphs: [
          "Verified open means the job was found on its source at the last check. If ERIO has not confirmed a job for 72 hours, the card says so. When a job disappears from its source it is marked closed, and its page stays reachable with that status.",
        ],
      },
      {
        heading: "The sources table",
        paragraphs: [
          "The same job is often listed on more than one platform. ERIO merges those into one job and keeps every listing in the Sources table: the platform, the listing, when it was first seen, when it was last checked and whether it is still listed. The first one is the primary listing, the one the Apply button uses.",
          "If a job page offers a History, it shows what changed since ERIO first saw the job, such as a pay change or a closing and reopening.",
        ],
      },
      {
        heading: "Why this matters",
        paragraphs: [
          "Roles that stay open for a long time, or that open and close repeatedly, are often hiring continuously. Pay changes in the history can also tell you whether an employer has raised an offer to fill a role.",
        ],
      },
    ],
    links: [
      { label: "Newest jobs first", href: "/search?sort=recent" },
      { label: "Platforms and how they are doing", href: "/coverage" },
      { label: "Market pulse: how fresh the index is", href: "/pulse" },
    ],
  },
  {
    slug: "privacy",
    title: "How ERIO treats your privacy",
    description: "What the site stores, what it does not, and how to use ERIO without handing over anything.",
    sections: [
      {
        heading: "No account, no profile",
        paragraphs: [
          "You can use every page without registering. ERIO does not ask who you are, and it does not build a profile of what you search for. The Apply button sends you to the employer's own page; what you tell the employer there is between you and them.",
        ],
      },
      {
        heading: "What your browser keeps",
        paragraphs: [
          "The site sets no tracking cookies and loads no advertising or analytics scripts. At the time of writing the only thing it stores in your browser is your choice of light or dark theme. Searches live in the address of the page, so they can be shared or bookmarked, and the back button works.",
        ],
      },
      {
        heading: "What the servers see",
        paragraphs: [
          "A search is sent to ERIO's servers to be answered, and like any server they keep operational logs of requests. The connecting network address is used to apply request limits, which stop one visitor from overloading the service.",
        ],
      },
      {
        heading: "Staying careful",
        paragraphs: [
          "A real employer does not ask you to pay to apply. If a job page leads you somewhere that asks for money, a government ID before an interview or a bank login, leave it. Pages you reach by Apply are outside ERIO's control.",
        ],
      },
    ],
    links: [
      { label: "Search without an account", href: "/search" },
      { label: "How ERIO gets its jobs", href: "/guides/how-erio-gets-its-jobs" },
    ],
  },
  {
    slug: "how-erio-gets-its-jobs",
    title: "How ERIO gets its jobs, and what it will not read",
    description: "Where the jobs come from, how often they are refreshed, and the sites ERIO leaves alone.",
    sections: [
      {
        heading: "From employers' own pages",
        paragraphs: [
          "ERIO reads the public job lists that employers publish through applicant tracking systems (the software companies use to post jobs), and a smaller number of job boards through feeds. It finds an employer's list, reads it on a schedule and turns each posting into the same shape: title, employer, place, remote scope, pay and a link to apply.",
          "Postings are cleaned and the same job posted on several platforms is merged. When a job disappears from its source it is marked closed on the next read.",
        ],
      },
      {
        heading: "What it will not read",
        paragraphs: [
          "ERIO does not collect from job boards whose terms forbid automated reading, such as LinkedIn, Indeed, Glassdoor and ZipRecruiter. It honours each site's robots.txt and crawl delay, reads each host slowly, and does not work around a block. A platform that turns crawlers away is listed as Blocked on the coverage page until it agrees.",
          "It also does not copy a posting's apply flow. You apply on the employer's page.",
        ],
      },
      {
        heading: "What this means for you",
        paragraphs: [
          "ERIO covers the employers whose lists it has found, not every job in the world, and coverage is uneven across countries. The coverage page shows which platforms are read and how healthy each one is, and the market pulse shows how many companies and roles the index holds right now.",
          "If you do not find an employer you expect, search its name; ERIO cannot show jobs from a platform it does not read.",
        ],
      },
    ],
    links: [
      { label: "Coverage by platform", href: "/coverage" },
      { label: "Companies hiring", href: "/companies" },
      { label: "Market pulse", href: "/pulse" },
    ],
  },
];

export const guideBySlug = (slug: string): Guide | undefined => GUIDES.find((g) => g.slug === slug);
