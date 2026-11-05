// Server-side client for the ERIO /v1 API. The website calls the same public
// API as outside clients (spec section 8); every number on the site comes from it.

const API_URL = process.env.ERIO_API_URL ?? "http://localhost:8000";

export type ApiHealth = { status: string; version: string };

export type JobRecord = {
  canonical_id: string;
  title: string;
  company: { name: string; domain: string | null; logo_url: string | null };
  role_category: string;
  location_text: string | null;
  city: string | null;
  region: string | null;
  country_code: string | null;
  lat: number | null;
  lon: number | null;
  remote_status: "remote" | "hybrid" | "onsite";
  remote_scope: "country" | "region" | "worldwide" | null;
  eligible_country_codes: string[];
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_period: "year" | "month" | "hour" | null;
  salary_usd_annual_min: number | null;
  status: "open" | "closed" | "unknown";
  posted_at: string | null;
  indexed_at: string;
  last_verified_at: string | null;
  closed_at: string | null;
  sources: string[];
  dedup_method: string | null;
  apply_url: string;
  description_html: string | null;
  description_text: string | null;
};

export type JobsPage = {
  data: JobRecord[];
  meta: {
    total: number;
    next_cursor: string | null;
    facets: {
      country: Record<string, number>;
      role: Record<string, number>;
      remote_status: Record<string, number>;
    };
  };
};

export type Country = {
  code: string;
  name: string;
  region: string | null;
  subregion: string | null;
  region_groups: string[];
  lat: number;
  lon: number;
  job_count: number;
  local_job_count: number;
  cities: { name: string; lat: number; lon: number; job_count: number }[];
};

export type Countries = {
  data: Country[];
  meta: { countries: number; countries_with_jobs: number; worldwide_remote_jobs: number };
};

export type Platform = {
  slug: string;
  name: string;
  kind: string;
  status: "live" | "indexing" | "scheduled" | "paused";
  boards: number;
  job_count: number;
  last_success_at: string | null;
  fetch_success_rate_24h: number | null;
};

export type Stats = {
  total_jobs: number;
  remote_jobs: number;
  worldwide_remote_jobs: number;
  countries_with_jobs: number;
  sources_live: number;
  boards_tracked: number;
  last_refresh_at: string | null;
  refresh_lag_minutes: number | null;
};

export class ApiUnavailable extends Error {}

type Params = Record<string, string | number | boolean | undefined | null>;

export function apiUrl(path: string, params: Params = {}): string {
  const url = new URL(path, API_URL);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }
  return url.toString();
}

async function get<T>(path: string, params: Params = {}, revalidate = 0): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path, params), {
      ...(revalidate ? { next: { revalidate } } : { cache: "no-store" as const }),
      signal: AbortSignal.timeout(8000),
    });
  } catch (error) {
    throw new ApiUnavailable(`ERIO API unreachable: ${String(error)}`);
  }
  if (response.status === 404) throw new NotFound(path);
  if (!response.ok) throw new ApiUnavailable(`ERIO API answered ${response.status} for ${path}`);
  return (await response.json()) as T;
}

export class NotFound extends Error {}

export async function getApiHealth(): Promise<ApiHealth | null> {
  try {
    return await get<ApiHealth>("/v1/health");
  } catch {
    return null;
  }
}

export const searchJobs = (params: Params) => get<JobsPage>("/v1/jobs", params);
export const getJob = (id: string) => get<{ data: JobRecord }>(`/v1/jobs/${encodeURIComponent(id)}`);
export const getCountries = () => get<Countries>("/v1/countries", {}, 60);
export const getPlatforms = () => get<{ data: Platform[] }>("/v1/platforms", {}, 60);
export const getStats = () => get<Stats>("/v1/stats", {}, 30);
export const getOpenApi = () => get<Record<string, unknown>>("/v1/openapi.json", {}, 300);

// The read-only MCP server (services/mcp) publishes its tools for OpenAI and
// Gemini function calling. Its address for people (and assistants) to use
// differs from the one this server reaches it at inside the stack.
const MCP_URL = process.env.ERIO_MCP_URL ?? "http://localhost:8100";
export const MCP_PUBLIC_URL = process.env.ERIO_MCP_PUBLIC_URL ?? "http://127.0.0.1:8100/mcp";

export async function getToolDefinitions(format: "openai" | "gemini"): Promise<unknown | null> {
  try {
    const response = await fetch(`${MCP_URL}/tools/${format}.json`, {
      next: { revalidate: 300 },
      signal: AbortSignal.timeout(5000),
    });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}
