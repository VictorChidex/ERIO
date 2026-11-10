import { type NextRequest, NextResponse } from "next/server";

import { apiUrl } from "@/lib/api";

// The browser talks to this route; this route talks to the API, which stays internal to the
// website. The workspace token travels from the browser's storage to the API as a header and
// is never written anywhere on the way (no logging, no cookie).

export const dynamic = "force-dynamic";

const WORKSPACE_PARTS = new Set(["applications", "saved-ids", "searches", "export", "import"]);
const MAX_BODY = 2.2 * 1024 * 1024;

type Context = { params: Promise<{ path?: string[] }> };

/** Map /workspace/api/<path> to the API path, or null when the path is not one we forward. */
function target(path: string[]): string | null {
  if (path.some((part) => !/^[A-Za-z0-9_.-]{1,80}$/.test(part) || part === "." || part === "..")) return null;
  if (path[0] === "match") return `/v1/${path.join("/")}`;
  if (path.length === 0) return "/v1/workspace";
  if (WORKSPACE_PARTS.has(path[0] ?? "")) return `/v1/workspace/${path.join("/")}`;
  return null;
}

async function forward(request: NextRequest, context: Context): Promise<NextResponse> {
  const path = (await context.params).path ?? [];
  const upstream = target(path);
  if (upstream === null) return NextResponse.json({ error: "not found" }, { status: 404 });

  const headers: Record<string, string> = {};
  const token = request.headers.get("x-workspace-token");
  if (token) headers["X-Workspace-Token"] = token;
  const hasBody = request.method !== "GET" && request.method !== "DELETE";
  let body: string | undefined;
  if (hasBody) {
    body = await request.text();
    if (body.length > MAX_BODY) return NextResponse.json({ error: "too large" }, { status: 413 });
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(apiUrl(upstream), {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(20000),
    });
  } catch {
    return NextResponse.json({ error: { message: "the workspace service is unreachable right now" } }, { status: 503 });
  }
  const out = new NextResponse(response.status === 204 ? null : await response.text(), {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") ?? "application/json", "Cache-Control": "no-store" },
  });
  const retry = response.headers.get("retry-after");
  if (retry) out.headers.set("Retry-After", retry);
  return out;
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const DELETE = forward;
