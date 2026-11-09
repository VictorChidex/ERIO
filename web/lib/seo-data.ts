// Data for the search-engine pages: landing-page job lists, the job detail
// with its sources, and the sitemap's list of pages worth indexing.
// Calls the public API like every other page; results are cached for an hour.

import type { Metadata } from "next";

import { ApiUnavailable, apiUrl, type Country, getCountries, type JobRecord, type JobsPage, NotFound } from "./api";
import { ROLE_LABELS } from "./format";
import type { HistoryEvent } from "./history";
import {
  absoluteUrl,
  countryBySlug,
  countrySlugs,
  headline,
  inSitemap,
  JOB_TITLES,
  type JobTitle,
  type Landing,
  landingPath,
  pageDescription,
  pageTitle,
  resolveSegment,
  robotsFor,
  SITEMAP_MIN,
  type SitemapUrl,
  titleBySlug,
  TITLE_COUNTRY_LIMIT,
} from "./seo";

/** Seconds a landing page's data, and the sitemap, may be served from cache. */
export const REVALIDATE = 3600;

type Params = Record<string, string | number | boolean | undefined>;

async function fetchJson<T>(path: string, params: Params = {}, revalidate = REVALIDATE): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path, params), {
      ...(revalidate ? { next: { revalidate } } : { cache: "no-store" as const }),
      signal: AbortSignal.timeout(8000),
    });
  } catch (error) {
    throw new ApiUnavailable(`ERIO API unreachable: ${String(error)}`);
  }
  if (response.status === 404) throw new NotFound(path);
  if (!response.ok) throw new ApiUnavailable(`ERIO API answered ${response.status} for ${path}`);
  return (await response.json()) as T;
}

/** The API filters that select a landing page's jobs. */
export function landingParams(landing: Landing): Params {
  switch (landing.kind) {
    case "country":
      return { country: landing.country.code, include_worldwide: false };
    case "country-role":
      return { country: landing.country.code, include_worldwide: false, role: landing.role };
    case "country-title":
      return { country: landing.country.code, include_worldwide: false, q: landing.title.query };
    case "country-city":
      return { country: landing.country.code, include_worldwide: false, location: landing.city };
    case "role-title":
      return { q: landing.title.query };
  }
}

export const landingJobs = (landing: Landing, perPage = 25) =>
  fetchJson<JobsPage>("/v1/jobs", { ...landingParams(landing), per_page: perPage, sort: "recent" });

export type ResolvedLanding = {
  landing: Landing;
  countries: Country[];
  slugs: Map<string, string>;
  /** The page's country, with its cities; absent on /jobs/role pages. */
  country: Country | null;
};

/** Turns URL segments into a landing page, or null when no such page exists. */
export async function resolveLanding(
  parts: { country?: string; segment?: string; title?: string },
): Promise<ResolvedLanding | null> {
  const countries = await countryList();
  const slugs = countrySlugs(countries);
  if (parts.title !== undefined) {
    const title = titleBySlug(parts.title);
    return title ? { landing: { kind: "role-title", title }, countries, slugs, country: null } : null;
  }
  const country = parts.country === undefined ? undefined : countryBySlug(countries, parts.country);
  if (!country) return null;
  const ref = { code: country.code, name: country.name };
  if (parts.segment === undefined) return { landing: { kind: "country", country: ref }, countries, slugs, country };
  const segment = resolveSegment(parts.segment, country.cities);
  if (!segment) return null;
  const landing: Landing =
    segment.kind === "role"
      ? { kind: "country-role", country: ref, role: segment.role }
      : segment.kind === "title"
        ? { kind: "country-title", country: ref, title: segment.title }
        : { kind: "country-city", country: ref, city: segment.city };
  return { landing, countries, slugs, country };
}

/** The same page's parent: a country page for its sub-pages. */
export const parentLanding = (landing: Landing): Landing | null =>
  landing.kind === "country" || landing.kind === "role-title" ? null : { kind: "country", country: landing.country };

export async function landingMetadata(resolved: ResolvedLanding): Promise<Metadata> {
  const { landing, slugs } = resolved;
  const total = (await landingJobs(landing, 1)).meta.total;
  const path = landingPath(landing, slugs);
  return {
    title: pageTitle(landing, total, new Date().getFullYear()),
    description: pageDescription(landing, total),
    alternates: { canonical: absoluteUrl(path) },
    robots: robotsFor(total),
  };
}

/** Where each posting of a job was found (GET /v1/jobs/{id}, source_details). */
export type SourceDetail = {
  platform: string;
  board_token: string;
  listing_id: string;
  is_primary: boolean;
  first_seen_at: string;
  last_checked_at: string;
  status: "open" | "missing" | "closed";
};

/** `history` arrives only from API versions that record it; the page shows it when present. */
export type JobDetail = JobRecord & { source_details: SourceDetail[]; history?: HistoryEvent[] };

export const getJobDetail = (id: string) =>
  fetchJson<{ data: JobDetail }>(`/v1/jobs/${encodeURIComponent(id)}`, {}, 0);

export async function countryList(): Promise<Country[]> {
  return (await getCountries()).data;
}

/** Run ``task`` over ``items`` with at most ``limit`` in flight. */
async function pool<T, R>(items: T[], limit: number, task: (item: T) => Promise<R>): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let next = 0;
  const worker = async () => {
    for (let i = next++; i < items.length; i = next++) results[i] = await task(items[i] as T);
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}

const count = async (params: Params): Promise<number> =>
  (await fetchJson<JobsPage>("/v1/jobs", { ...params, per_page: 1 })).meta.total;

/** Open jobs per curated title worldwide, biggest first (one cached call per title). */
export async function titleTotals(): Promise<{ title: JobTitle; total: number }[]> {
  const totals = await pool(JOB_TITLES, 6, async (title) => ({ title, total: await count({ q: title.query }) }));
  return totals.sort((a, b) => b.total - a.total);
}

export type PopularLink = { label: string; href: string };

/**
 * "Popular searches" for the home page: the biggest countries, the biggest
 * job titles, and the top roles of the three biggest countries. Only pages
 * with enough jobs to be indexed are linked. Every call is cached for an hour.
 */
export async function popularSearches(): Promise<{ countries: PopularLink[]; titles: PopularLink[]; roles: PopularLink[] }> {
  const all = await countryList();
  const slugs = countrySlugs(all);
  const big = all.filter((c) => inSitemap(c.local_job_count)).sort((a, b) => b.local_job_count - a.local_job_count);
  const ref = (c: Country) => ({ code: c.code, name: c.name });
  const countries = big.slice(0, 12).map((c) => ({
    label: headline({ kind: "country", country: ref(c) }),
    href: landingPath({ kind: "country", country: ref(c) }, slugs),
  }));
  const titles = (await titleTotals())
    .filter((t) => inSitemap(t.total))
    .slice(0, 8)
    .map(({ title }) => ({
      label: headline({ kind: "role-title", title }),
      href: landingPath({ kind: "role-title", title }, slugs),
    }));
  const roles = (
    await Promise.all(
      big.slice(0, 3).map(async (c) => {
        const facets = (
          await fetchJson<JobsPage>("/v1/jobs", { country: c.code, include_worldwide: false, per_page: 1 })
        ).meta.facets.role;
        return Object.entries(facets)
          .filter(([role, n]) => role !== "other" && inSitemap(n))
          .sort((a, b) => b[1] - a[1])
          .slice(0, 3)
          .map(([role]) => {
            const landing: Landing = { kind: "country-role", country: ref(c), role };
            return { label: headline(landing), href: landingPath(landing, slugs) };
          });
      }),
    )
  ).flat();
  return { countries, titles, roles };
}

/**
 * Every landing page worth listing in the sitemap, with its job count.
 *
 * API calls stay few: one facet call per country with enough local jobs (its
 * `facets.role` gives every role page's count at once), the cities' counts
 * come free from /v1/countries, and titles are counted once worldwide before
 * being tried in the TITLE_COUNTRY_LIMIT biggest countries.
 */
export async function sitemapLandings(): Promise<{ landing: Landing; total: number }[]> {
  const countries = (await countryList()).filter((c) => c.local_job_count >= SITEMAP_MIN);
  const found: { landing: Landing; total: number }[] = [];

  const facetCalls = await pool(countries, 6, async (country) => ({
    country,
    page: await fetchJson<JobsPage>("/v1/jobs", {
      country: country.code,
      include_worldwide: false,
      per_page: 1,
    }),
  }));
  for (const { country, page } of facetCalls) {
    const ref = { code: country.code, name: country.name };
    if (inSitemap(page.meta.total)) found.push({ landing: { kind: "country", country: ref }, total: page.meta.total });
    for (const role of Object.keys(ROLE_LABELS)) {
      const total = page.meta.facets.role[role] ?? 0;
      if (inSitemap(total)) found.push({ landing: { kind: "country-role", country: ref, role }, total });
    }
    for (const city of country.cities) {
      if (inSitemap(city.job_count)) {
        found.push({ landing: { kind: "country-city", country: ref, city: city.name }, total: city.job_count });
      }
    }
  }

  const common = (await titleTotals()).filter((t) => inSitemap(t.total));
  for (const { title, total } of common) found.push({ landing: { kind: "role-title", title }, total });

  const biggest = [...countries].sort((a, b) => b.local_job_count - a.local_job_count).slice(0, TITLE_COUNTRY_LIMIT);
  const pairs = biggest.flatMap((country) => common.map(({ title }) => ({ country, title })));
  const pairTotals = await pool(pairs, 6, ({ country, title }) =>
    count({ country: country.code, include_worldwide: false, q: title.query }),
  );
  pairs.forEach(({ country, title }, i) => {
    const total = pairTotals[i] ?? 0;
    if (inSitemap(total)) {
      found.push({
        landing: { kind: "country-title", country: { code: country.code, name: country.name }, title },
        total,
      });
    }
  });
  return found;
}

let memo: { at: number; urls: SitemapUrl[] } | null = null;

/** Sitemap entries for the curated landing pages, computed at most once an hour per server. */
export async function landingSitemapUrls(): Promise<SitemapUrl[]> {
  if (memo && Date.now() - memo.at < REVALIDATE * 1000) return memo.urls;
  const countries = await countryList();
  const slugs = countrySlugs(countries);
  const urls = (await sitemapLandings()).map(({ landing }) => ({ loc: absoluteUrl(landingPath(landing, slugs)) }));
  const seen = new Set<string>();
  const unique = urls.filter((u) => !seen.has(u.loc) && seen.add(u.loc));
  memo = { at: Date.now(), urls: unique };
  return unique;
}
