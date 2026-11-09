import { ApiUnavailable } from "@/lib/api";
import { urlsetXml } from "@/lib/seo";
import { companyShardCount, companyShardUrls } from "@/lib/seo-companies";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ shard: string }> };

/** One shard of /company/{slug} pages: `/sitemaps/companies/1.xml`, 1-based. */
export async function GET(_request: Request, { params }: Props): Promise<Response> {
  const match = /^([1-9][0-9]*)\.xml$/.exec((await params).shard);
  if (!match) return new Response("Not found", { status: 404 });
  const shard = Number(match[1]);
  try {
    if (shard > (await companyShardCount())) return new Response("Not found", { status: 404 });
    return new Response(urlsetXml(await companyShardUrls(shard)), {
      headers: {
        "content-type": "application/xml; charset=utf-8",
        "cache-control": "public, s-maxage=3600, stale-while-revalidate=86400",
      },
    });
  } catch (error) {
    if (error instanceof ApiUnavailable) {
      console.error("company sitemap: the company list could not be read:", error);
      return new Response("The company list is unavailable.", { status: 503, headers: { "retry-after": "300" } });
    }
    throw error;
  }
}
