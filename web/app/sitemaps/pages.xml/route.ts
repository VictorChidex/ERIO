import { ApiUnavailable } from "@/lib/api";
import { urlsetXml } from "@/lib/seo";
import { fixedSitemapUrls, landingSitemapUrls } from "@/lib/seo-data";

export const dynamic = "force-dynamic";

/** The home page plus every curated landing page that has enough open jobs. */
export async function GET(): Promise<Response> {
  try {
    const landings = await landingSitemapUrls();
    return new Response(urlsetXml([...fixedSitemapUrls(), ...landings]), {
      headers: {
        "content-type": "application/xml; charset=utf-8",
        "cache-control": "public, s-maxage=3600, stale-while-revalidate=86400",
      },
    });
  } catch (error) {
    if (error instanceof ApiUnavailable) {
      console.error("sitemap: the job index could not be read:", error);
      // Better a short outage than a sitemap that tells crawlers the pages are gone.
      return new Response("The job index is unavailable.", { status: 503, headers: { "retry-after": "300" } });
    }
    throw error;
  }
}
