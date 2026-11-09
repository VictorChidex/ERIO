// Company sitemap shards.
//
// The sitemap index (app/sitemap.xml/route.ts) lists `pages.xml` plus one
// `companies/N.xml` per shard reported here, and app/sitemaps/companies/[shard]
// serves each one. A shard lists /company/{slug} for the companies that have
// open roles, SITEMAP_MAX_URLS to a shard, read from GET /v1/companies in
// name order so a company stays in the same shard between runs.

import { ApiUnavailable, type Companies, getCompanies } from "./api";
import { absoluteUrl, SITEMAP_MAX_URLS, type SitemapUrl } from "./seo";

/** The API's largest page of companies. */
export const COMPANY_PAGE_SIZE = 100;

/** Pages of COMPANY_PAGE_SIZE that fill one shard. */
export const PAGES_PER_SHARD = Math.floor(SITEMAP_MAX_URLS / COMPANY_PAGE_SIZE);

/** Shards needed for ``total`` companies (none when there are none). */
export const shardsFor = (total: number): number => Math.ceil(total / SITEMAP_MAX_URLS);

/** The API pages a 1-based shard covers, clipped to ``total`` companies. */
export function shardPages(shard: number, total: number): number[] {
  const first = (shard - 1) * PAGES_PER_SHARD + 1;
  const last = Math.min(shard * PAGES_PER_SHARD, Math.ceil(total / COMPANY_PAGE_SIZE));
  return Array.from({ length: Math.max(0, last - first + 1) }, (_, i) => first + i);
}

export const companyUrl = (slug: string): SitemapUrl => ({ loc: absoluteUrl(`/company/${encodeURIComponent(slug)}`) });

const MEMO_MS = 3_600_000;
const page = (n: number, per = COMPANY_PAGE_SIZE) =>
  getCompanies({ hiring_only: true, sort: "name", per_page: per, page: n });

let totalMemo: { at: number; total: number } | null = null;

async function companyTotal(): Promise<number> {
  if (totalMemo && Date.now() - totalMemo.at < MEMO_MS) return totalMemo.total;
  const total = (await page(1, 1)).meta.total;
  totalMemo = { at: Date.now(), total };
  return total;
}

export async function companyShardCount(): Promise<number> {
  try {
    return shardsFor(await companyTotal());
  } catch (error) {
    // While the API is down the index lists the pages shard alone, rather than failing whole.
    if (error instanceof ApiUnavailable) return 0;
    throw error;
  }
}

export async function companyShardUrls(shard: number): Promise<SitemapUrl[]> {
  const pages = shardPages(shard, await companyTotal());
  const results: Companies[] = new Array(pages.length);
  let next = 0;
  const worker = async () => {
    for (let i = next++; i < pages.length; i = next++) results[i] = await page(pages[i] as number);
  };
  await Promise.all(Array.from({ length: Math.min(6, pages.length) }, worker));
  return results.flatMap((r) => r.data.map((c) => companyUrl(c.slug)));
}
