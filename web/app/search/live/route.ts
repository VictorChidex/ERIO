import { type NextRequest, NextResponse } from "next/server";

import { ApiUnavailable, startRefresh } from "@/lib/api";
import { parseFilters, toApiParams } from "@/lib/filters";

// Starts a live refresh for the search the page shows: the API re-reads the employer boards
// behind its results. Called from the browser, so the API stays internal to the website.
export async function POST(request: NextRequest) {
  const filters = parseFilters(Object.fromEntries(request.nextUrl.searchParams.entries()));
  const { q, country, include_worldwide, remote_status, role, salary_min_usd } = toApiParams(filters);
  try {
    const refresh = await startRefresh({ q, country, include_worldwide, remote_status, role, salary_min_usd });
    return NextResponse.json(refresh, { status: 202 });
  } catch (error) {
    if (error instanceof ApiUnavailable) {
      return NextResponse.json({ error: "live refresh is unavailable right now" }, { status: 503 });
    }
    throw error;
  }
}
