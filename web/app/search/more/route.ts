import { type NextRequest, NextResponse } from "next/server";

import { ApiUnavailable, searchJobs } from "@/lib/api";
import { parseFilters, toApiParams } from "@/lib/filters";

// The next page of results for "Load more", fetched server-side so the API
// stays internal to the website.
export async function GET(request: NextRequest) {
  const params = Object.fromEntries(request.nextUrl.searchParams.entries());
  const filters = parseFilters(params);
  try {
    const page = await searchJobs(toApiParams(filters));
    return NextResponse.json({ data: page.data, next_cursor: page.meta.next_cursor });
  } catch (error) {
    if (error instanceof ApiUnavailable) {
      return NextResponse.json({ error: "search is unavailable right now" }, { status: 503 });
    }
    throw error;
  }
}
