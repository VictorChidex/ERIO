// Server-side client for the ERIO /v1 API. The website calls the same public
// API as outside clients; only the base address is configured here.

const API_URL = process.env.ERIO_API_URL ?? "http://localhost:8000";

export type ApiHealth = { status: string; version: string };

export async function getApiHealth(): Promise<ApiHealth | null> {
  try {
    const response = await fetch(`${API_URL}/v1/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2000),
    });
    if (!response.ok) return null;
    return (await response.json()) as ApiHealth;
  } catch {
    return null;
  }
}
