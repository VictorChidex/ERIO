// Search-engine pages: slugs, thresholds, titles, robots.txt and JSON-LD.
// Everything here is pure (no network, no Next.js imports) so the unit tests
// in e2e/seo.unit.ts can run it directly. The data side is lib/seo-data.ts.

import { ROLE_LABELS } from "./format";

/** Public origin of the website, used for canonical URLs and the sitemap. */
export const SITE_URL = (process.env.ERIO_SITE_URL ?? "http://localhost:3000").replace(/\/+$/, "");

/** A landing page with fewer open jobs than this is served noindex (it still follows links). */
export const THIN_PAGE_MIN = 5;

/** The sitemap lists only landing pages with at least this many jobs, so it stays well above "thin". */
export const SITEMAP_MIN = 10;

/** Countries that also get "<title> jobs in <country>" pages in the sitemap (the biggest ones). */
export const TITLE_COUNTRY_LIMIT = 8;

/** Largest sitemap file: the protocol allows 50,000 URLs. */
export const SITEMAP_MAX_URLS = 50_000;

export type JobTitle = {
  slug: string;
  /** Heading words: "Electrician jobs in Germany". */
  label: string;
  /** What the search box is given to find this title. */
  query: string;
};

/** Curated job titles that get their own pages. Keep slugs distinct from ROLE_LABELS keys. */
export const JOB_TITLES: JobTitle[] = [
  { slug: "nurse", label: "Nurse", query: "nurse" },
  { slug: "driver", label: "Driver", query: "driver" },
  { slug: "teacher", label: "Teacher", query: "teacher" },
  { slug: "electrician", label: "Electrician", query: "electrician" },
  { slug: "warehouse", label: "Warehouse worker", query: "warehouse" },
  { slug: "cashier", label: "Cashier", query: "cashier" },
  { slug: "accountant", label: "Accountant", query: "accountant" },
  { slug: "software-engineer", label: "Software engineer", query: "software engineer" },
  { slug: "data-analyst", label: "Data analyst", query: "data analyst" },
  { slug: "data-scientist", label: "Data scientist", query: "data scientist" },
  { slug: "product-manager", label: "Product manager", query: "product manager" },
  { slug: "designer", label: "Designer", query: "designer" },
  { slug: "project-manager", label: "Project manager", query: "project manager" },
  { slug: "customer-support", label: "Customer support agent", query: "customer support" },
  { slug: "sales-representative", label: "Sales representative", query: "sales representative" },
  { slug: "marketing-manager", label: "Marketing manager", query: "marketing manager" },
  { slug: "recruiter", label: "Recruiter", query: "recruiter" },
  { slug: "mechanic", label: "Mechanic", query: "mechanic" },
  { slug: "chef", label: "Chef", query: "chef" },
  { slug: "security-guard", label: "Security guard", query: "security guard" },
  { slug: "pharmacist", label: "Pharmacist", query: "pharmacist" },
  { slug: "receptionist", label: "Receptionist", query: "receptionist" },
];

export function titleBySlug(slug: string): JobTitle | undefined {
  return JOB_TITLES.find((t) => t.slug === slug);
}

export const roleLabel = (role: string): string => ROLE_LABELS[role] ?? role;

/** Lower-case ASCII words joined by dashes: "São Paulo" -> "sao-paulo". */
export function slugify(text: string): string {
  return text
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export type CountryRef = { code: string; name: string };

/**
 * Slug for every country, from the names /v1/countries returns. Two countries
 * that would share a slug both get their ISO code appended, so a slug always
 * maps back to exactly one country.
 */
export function countrySlugs(countries: CountryRef[]): Map<string, string> {
  const seen = new Map<string, number>();
  for (const c of countries) seen.set(slugify(c.name), (seen.get(slugify(c.name)) ?? 0) + 1);
  const slugs = new Map<string, string>();
  for (const c of countries) {
    const base = slugify(c.name);
    slugs.set(c.code, (seen.get(base) ?? 0) > 1 ? `${base}-${c.code.toLowerCase()}` : base);
  }
  return slugs;
}

export function countryBySlug<T extends CountryRef>(countries: T[], slug: string): T | undefined {
  const slugs = countrySlugs(countries);
  return countries.find((c) => slugs.get(c.code) === slug);
}

export type Landing =
  | { kind: "country"; country: CountryRef }
  | { kind: "country-role"; country: CountryRef; role: string }
  | { kind: "country-title"; country: CountryRef; title: JobTitle }
  | { kind: "country-city"; country: CountryRef; city: string }
  | { kind: "role-title"; title: JobTitle };

/** What the second path segment under /jobs/in/{country} names. */
export type Segment =
  | { kind: "role"; role: string }
  | { kind: "title"; title: JobTitle }
  | { kind: "city"; city: string };

/** Role category first, then curated title, then one of the country's cities. */
export function resolveSegment(slug: string, cities: { name: string }[]): Segment | null {
  if (slug in ROLE_LABELS) return { kind: "role", role: slug };
  const title = titleBySlug(slug);
  if (title) return { kind: "title", title };
  const city = cities.find((c) => slugify(c.name) === slug);
  return city ? { kind: "city", city: city.name } : null;
}

/** "Jobs", "Electrician jobs", "Healthcare jobs": the plural noun phrase of a page. */
export const noun = (landing: Landing): string => {
  switch (landing.kind) {
    case "country":
      return "Jobs";
    case "country-role":
      return `${roleLabel(landing.role)} jobs`;
    case "country-title":
    case "role-title":
      return `${landing.title.label} jobs`;
    case "country-city":
      return "Jobs";
  }
};

/** "Electrician jobs in Germany" — the page's H1. */
export function headline(landing: Landing): string {
  switch (landing.kind) {
    case "country":
      return `Jobs in ${landing.country.name}`;
    case "country-role":
    case "country-title":
      return `${noun(landing)} in ${landing.country.name}`;
    case "country-city":
      return `Jobs in ${landing.city}, ${landing.country.name}`;
    case "role-title":
      return noun(landing);
  }
}

export function landingPath(landing: Landing, slugs: Map<string, string>): string {
  const slugOf = (c: CountryRef) => slugs.get(c.code) ?? slugify(c.name);
  switch (landing.kind) {
    case "country":
      return `/jobs/in/${slugOf(landing.country)}`;
    case "country-role":
      return `/jobs/in/${slugOf(landing.country)}/${landing.role}`;
    case "country-title":
      return `/jobs/in/${slugOf(landing.country)}/${landing.title.slug}`;
    case "country-city":
      return `/jobs/in/${slugOf(landing.country)}/${slugify(landing.city)}`;
    case "role-title":
      return `/jobs/role/${landing.title.slug}`;
  }
}

/** True when a page with this many open jobs should be kept out of the index. */
export const isThin = (total: number): boolean => total < THIN_PAGE_MIN;

/** True when the sitemap should list a page with this many open jobs. */
export const inSitemap = (total: number): boolean => total >= SITEMAP_MIN;

export function robotsFor(total: number): { index: boolean; follow: true } {
  return { index: !isThin(total), follow: true };
}

export function pageTitle(landing: Landing, total: number, year: number): string {
  const jobs = `${total} open ${total === 1 ? "role" : "roles"}`;
  return `${headline(landing)} — ${jobs} (${year})`;
}

export function pageDescription(landing: Landing, total: number): string {
  const what = landing.kind === "country" || landing.kind === "country-city" ? "jobs" : noun(landing);
  const place = landing.kind === "role-title" ? "" : ` in ${placeName(landing)}`;
  return `${total} open ${what}${place} from company career pages and job boards, refreshed every hour. Compare employers and cities, then apply at the source.`;
}

function placeName(landing: Landing): string {
  if (landing.kind === "country-city") return `${landing.city}, ${landing.country.name}`;
  if (landing.kind === "role-title") return "";
  return landing.country.name;
}

export const absoluteUrl = (path: string): string => `${SITE_URL}${path}`;

export type Crumb = { name: string; path: string };

export function breadcrumbJsonLd(crumbs: Crumb[]): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((crumb, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: crumb.name,
      item: absoluteUrl(crumb.path),
    })),
  };
}

/** JSON for a <script> tag: "<" escaped so text in a job can never close the tag. */
export function scriptJson(value: unknown): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

/** Where a company's jobs are listed. Switch to the /company/{slug} page when that route ships. */
export const companyHref = (name: string): string => `/search?q=${encodeURIComponent(name)}`;

/** Job page title: "<Job title> at <Company> in <City, Country>". */
export function jobPageTitle(
  job: { title: string; company: { name: string }; city: string | null; country_code: string | null },
  countryNames: Record<string, string>,
): string {
  const country = job.country_code ? (countryNames[job.country_code] ?? job.country_code) : null;
  const place = [job.city, country].filter(Boolean).join(", ");
  return `${job.title} at ${job.company.name}${place ? ` in ${place}` : ""}`;
}

/** The first lines of the job text as a meta description (at most ``max`` characters). */
export function snippet(text: string | null, fallback: string, max = 160): string {
  const flat = (text ?? "").replace(/\s+/g, " ").trim();
  if (!flat) return fallback;
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max - 1);
  return `${cut.slice(0, cut.lastIndexOf(" ") > 80 ? cut.lastIndexOf(" ") : cut.length)}…`;
}

/** Crawlers that collect text to train AI models; they are asked to stay away. */
export const AI_TRAINING_CRAWLERS = [
  "GPTBot",
  "ClaudeBot",
  "anthropic-ai",
  "CCBot",
  "Google-Extended",
  "Bytespider",
  "Applebot-Extended",
  "Amazonbot",
  "Diffbot",
  "cohere-ai",
  "FacebookBot",
  "Meta-ExternalAgent",
  "PerplexityBot",
  "omgili",
  "ImagesiftBot",
];

/** robots.txt body. A function (not a constant) so tests can check it. */
export function robotsTxt(siteUrl: string = SITE_URL): string {
  const lines = [
    "# ERIO job index.",
    "# Wanting the data? Use the public API (/api) or the MCP server instead of crawling pages.",
    "",
    "User-agent: *",
    "Allow: /",
    "# Filtered search URLs are an endless space; the landing pages under /jobs/in/ and /jobs/role/ cover what matters.",
    "Disallow: /search",
    "Disallow: /jobs?",
    "Allow: /jobs?page=",
    "Disallow: /api/",
    "Content-Signal: search=yes, ai-input=yes, ai-train=no",
    "",
  ];
  for (const agent of AI_TRAINING_CRAWLERS) {
    lines.push(`User-agent: ${agent}`, "Disallow: /", "Content-Signal: search=no, ai-input=no, ai-train=no", "");
  }
  lines.push(`Sitemap: ${siteUrl}/sitemap.xml`, "");
  return lines.join("\n");
}

export type SitemapUrl = { loc: string; lastmod?: string };

const xmlEscape = (text: string): string =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function urlsetXml(urls: SitemapUrl[]): string {
  const rows = urls.slice(0, SITEMAP_MAX_URLS).map(
    (u) => `<url><loc>${xmlEscape(u.loc)}</loc>${u.lastmod ? `<lastmod>${u.lastmod}</lastmod>` : ""}</url>`,
  );
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${rows.join("\n")}\n</urlset>\n`;
}

export function sitemapIndexXml(locs: SitemapUrl[]): string {
  const rows = locs.map(
    (u) => `<sitemap><loc>${xmlEscape(u.loc)}</loc>${u.lastmod ? `<lastmod>${u.lastmod}</lastmod>` : ""}</sitemap>`,
  );
  return `<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${rows.join("\n")}\n</sitemapindex>\n`;
}
