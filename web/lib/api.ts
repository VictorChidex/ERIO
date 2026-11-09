// Server-side client for the ERIO /v1 API. The website calls the same public
// API as outside clients (spec section 8); every number on the site comes from it.

const API_URL = process.env.ERIO_API_URL ?? "http://localhost:8000";

export type ApiHealth = { status: string; version: string };

export type JobRecord = {
  canonical_id: string;
  title: string;
  /** `slug` is null for records indexed before the slug was added to the index. */
  company: { name: string; slug?: string | null; domain: string | null; logo_url: string | null };
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

export type CoverageRow = {
  slug: string;
  name: string;
  kind: "ats" | "board";
  status: "Verified" | "Partial" | "Blocked" | "Failing" | "Built, not run live" | "Needs decision" | "Not built";
  boards_verified: number;
  jobs_read: number;
  partial_read: boolean;
  checked_at: string | null;
  note: string;
  // How the platform is doing now (shares are 0 to 1, null when it has no jobs).
  boards_total: number;
  boards_ok_2d: number;
  open_jobs: number;
  runs_7d_ok: number;
  runs_7d_failed: number;
  with_description: number | null;
  with_location: number | null;
  with_posted_date: number | null;
  with_salary: number | null;
  last_success_at: string | null;
  live: boolean;
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

// Market pulse and company pages (/v1/insights/pulse, /v1/companies).
export type Bucket = { key: string; label: string; count: number };
export type Place = Bucket;

/** Quartiles of each advertised range's midpoint, in the currency and period it was posted in. */
export type PayQuartiles = {
  currency: string;
  period: "year" | "month" | "hour";
  roles: number;
  lower: number;
  median: number;
  upper: number;
};

export type FlowDay = { date: string; added: number; removed: number };
export type Flow = {
  days: FlowDay[];
  added: number;
  removed: number;
  removals_tracked_since: string | null;
};

export type Pulse = {
  generated_at: string;
  totals: {
    open_roles: number;
    companies_hiring: number;
    sources_watched: number;
    platforms_live: number;
    roles_stating_pay: number;
    pay_stated_pct: number | null;
    remote_roles: number;
  };
  flow: Flow;
  posted: Bucket[];
  last_seen: Bucket[];
  roles: Bucket[];
  work_mode: Bucket[];
  pay: PayQuartiles[];
  countries: { code: string; name: string; roles: number; remote_pct: number | null; pay_stated_pct: number | null }[];
  sources: {
    platforms: { slug: string; name: string; kind: string; roles: number }[];
    ats_roles: number;
    board_roles: number;
  };
};

export type CompanyRow = {
  slug: string;
  name: string;
  domain: string | null;
  logo_url: string | null;
  country_code: string | null;
  open_roles: number;
};

export type Companies = { data: CompanyRow[]; meta: { total: number; page: number; per_page: number } };

export type CompanyProfile = {
  slug: string;
  name: string;
  domain: string | null;
  logo_url: string | null;
  country_code: string | null;
  tracked_since: string;
  last_checked_at: string | null;
  open_roles: number;
  added_30d: number;
  removed_30d: number;
  remote_pct: number | null;
  pay_stated_pct: number | null;
  flow: Flow;
  roles: Bucket[];
  countries: Place[];
  locations: Place[];
  work_mode: Bucket[];
  contracts: Bucket[];
  posted: Bucket[];
  pay: PayQuartiles[];
  platforms: { slug: string; name: string; kind: string; roles: number }[];
  latest: {
    canonical_id: string;
    title: string;
    location_text: string | null;
    country_code: string | null;
    remote_status: "remote" | "hybrid" | "onsite";
    employment_type: string | null;
    posted_at: string | null;
    indexed_at: string;
  }[];
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

/** Progress of a live refresh: the employer boards re-read for one search (/v1/search/refresh). */
export type Refresh = {
  id: string;
  boards: number;
  done: number;
  new_postings: number;
  changed_postings: number;
  finished: boolean;
  shared: boolean;
};

async function send<T>(method: "GET" | "POST", path: string, params: Params = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path, params), {
      method,
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
  } catch (error) {
    throw new ApiUnavailable(`ERIO API unreachable: ${String(error)}`);
  }
  if (response.status === 404) throw new NotFound(path);
  if (!response.ok) throw new ApiUnavailable(`ERIO API answered ${response.status} for ${path}`);
  return (await response.json()) as T;
}

export const startRefresh = (params: Params) => send<Refresh>("POST", "/v1/search/refresh", params);
export const getRefresh = (id: string) =>
  send<Refresh>("GET", `/v1/search/refresh/${encodeURIComponent(id)}`);
export const getJob = (id: string) => get<{ data: JobRecord }>(`/v1/jobs/${encodeURIComponent(id)}`);
export const getCountries = () => get<Countries>("/v1/countries", {}, 60);
export const getPlatforms = () => get<{ data: Platform[] }>("/v1/platforms", {}, 60);
export const getCoverage = () => get<{ data: CoverageRow[] }>("/v1/coverage", {}, 300);
export const getStats = () => get<Stats>("/v1/stats", {}, 30);
export const getPulse = () => get<{ data: Pulse }>("/v1/insights/pulse", {}, 60);
export const getCompanies = (params: Params) => get<Companies>("/v1/companies", params);
export const getCompany = (slug: string) =>
  get<{ data: CompanyProfile }>(`/v1/companies/${encodeURIComponent(slug)}`, {}, 60);
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
