import { robotsTxt } from "@/lib/seo";

// A route handler rather than app/robots.ts: the metadata API cannot write the
// Content-Signal line or the comment for people who want the data.
export function GET(): Response {
  return new Response(robotsTxt(), {
    headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "public, max-age=3600" },
  });
}
