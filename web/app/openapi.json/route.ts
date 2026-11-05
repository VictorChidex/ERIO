import { NextResponse } from "next/server";

import { ApiUnavailable, getOpenApi } from "@/lib/api";

// The API's OpenAPI 3.1 spec, served from the website for developers.
export async function GET() {
  try {
    return NextResponse.json(await getOpenApi());
  } catch (error) {
    if (error instanceof ApiUnavailable) {
      return NextResponse.json({ error: "the API spec is unavailable right now" }, { status: 503 });
    }
    throw error;
  }
}
