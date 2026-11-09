import { ApiUnavailable, getCountries, searchJobs } from "@/lib/api";
import { atomFeed, FEED_SIZE } from "@/lib/feed";
import { parseFilters, type RawParams, toApiParams, toQuery } from "@/lib/filters";

export const dynamic = "force-dynamic";

/**
 * Atom feed of a search: /feed.xml?q=nurse&country=NG&role=healthcare&type=remote&salary=1.
 * Same filters as /search; `new=1` keeps only jobs posted in the last 24 hours.
 */
export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const raw: RawParams = {};
  for (const key of new Set(url.searchParams.keys())) raw[key] = url.searchParams.getAll(key);
  const filters = { ...parseFilters(raw), sort: "recent" as const, cursor: null };
  const onlyNew = url.searchParams.get("new") === "1";
  try {
    const [page, countries] = await Promise.all([
      searchJobs({
        ...toApiParams(filters, FEED_SIZE),
        posted_after: onlyNew ? new Date(Date.now() - 24 * 3_600_000).toISOString() : undefined,
      }),
      getCountries().catch(() => ({ data: [] })),
    ]);
    const countryNames = Object.fromEntries(countries.data.map((c) => [c.code, c.name]));
    const query = toQuery(filters) + (onlyNew ? `${toQuery(filters) ? "&" : "?"}new=1` : "");
    const title = [onlyNew ? "New jobs" : "Jobs", filters.q && `for “${filters.q}”`, filters.countries.join(", ")]
      .filter(Boolean)
      .join(" ");
    return new Response(
      atomFeed({ title: `ERIO: ${title}`, selfPath: `/feed.xml${query}`, jobs: page.data, countryNames }),
      {
        headers: {
          "content-type": "application/atom+xml; charset=utf-8",
          "cache-control": "public, s-maxage=300, stale-while-revalidate=600",
        },
      },
    );
  } catch (error) {
    if (error instanceof ApiUnavailable) {
      return new Response("The job index is unavailable.", { status: 503, headers: { "retry-after": "300" } });
    }
    throw error;
  }
}
