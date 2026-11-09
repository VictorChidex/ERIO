import { type NextRequest, NextResponse } from "next/server";

import { apiUrl } from "@/lib/api";

// The public Atom feed of a saved search: /workspace/feed/<feed token>.atom. Any feed reader can
// follow it; the address is the only key and it opens nothing but that search's public matches.

export const dynamic = "force-dynamic";

export async function GET(_request: NextRequest, context: { params: Promise<{ file: string }> }) {
  const { file } = await context.params;
  const match = /^([A-Za-z0-9_-]{20,48})\.atom$/.exec(file);
  if (!match) return new NextResponse("not found", { status: 404 });
  let response: Response;
  try {
    response = await fetch(apiUrl(`/v1/feeds/${match[1]}.atom`), {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
  } catch {
    return new NextResponse("feed unavailable", { status: 503 });
  }
  if (!response.ok) return new NextResponse("not found", { status: response.status === 404 ? 404 : 503 });
  return new NextResponse(await response.text(), {
    headers: {
      "Content-Type": "application/atom+xml; charset=utf-8",
      "Cache-Control": "public, max-age=300",
      "X-Robots-Tag": "noindex",
    },
  });
}
