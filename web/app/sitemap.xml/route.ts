import { absoluteUrl, sitemapIndexXml } from "@/lib/seo";
import { companyShardCount } from "@/lib/seo-companies";

// Built per request (never at build time, when the API may be unreachable);
// the shard files it names are cached for an hour.
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  const shards = await companyShardCount();
  const locs = [
    { loc: absoluteUrl("/sitemaps/pages.xml") },
    ...Array.from({ length: shards }, (_, i) => ({ loc: absoluteUrl(`/sitemaps/companies/${i + 1}.xml`) })),
  ];
  return new Response(sitemapIndexXml(locs), {
    headers: {
      "content-type": "application/xml; charset=utf-8",
      "cache-control": "public, s-maxage=3600, stale-while-revalidate=86400",
    },
  });
}
