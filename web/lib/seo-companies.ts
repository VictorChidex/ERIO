// Extension point for the company sitemap shards.
//
// The sitemap index (app/sitemap.xml/route.ts) lists `pages.xml` plus one
// `companies/N.xml` per shard reported here, and each shard is served by
// app/sitemaps/companies/[shard]/route.ts. Whoever builds the /company/**
// pages: return the shard count from `companyShardCount` and the page URLs of
// shard N (1-based, at most SITEMAP_MAX_URLS each) from `companyShardUrls`,
// then add that route handler (it should strip the ".xml" suffix from the
// segment and answer with urlsetXml). Until then there are no shards.

import type { SitemapUrl } from "./seo";

export async function companyShardCount(): Promise<number> {
  return 0;
}

export async function companyShardUrls(shard: number): Promise<SitemapUrl[]> {
  void shard;
  return [];
}
