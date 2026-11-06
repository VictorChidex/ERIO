import { type NextRequest, NextResponse } from "next/server";

import { ApiUnavailable, getRefresh, NotFound } from "@/lib/api";

// Progress of a live refresh, for the page that started it.
export async function GET(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f]{32}$/.test(id)) return NextResponse.json({ error: "not a refresh" }, { status: 400 });
  try {
    return NextResponse.json(await getRefresh(id));
  } catch (error) {
    if (error instanceof NotFound) return NextResponse.json({ error: "refresh expired" }, { status: 404 });
    if (error instanceof ApiUnavailable) {
      return NextResponse.json({ error: "live refresh is unavailable right now" }, { status: 503 });
    }
    throw error;
  }
}
