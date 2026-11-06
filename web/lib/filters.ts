// Search filters live in the URL (spec section 8):
//   /search?country=NG,CA&ww=1&type=remote&role=engineering
// Links can be shared and the back button works. Repeated parameters
// (country=NG&country=CA, as a plain HTML form sends them) are read too.

import { ROLE_LABELS } from "./format";

export type Filters = {
  q: string;
  countries: string[];
  ww: boolean;
  types: string[];
  roles: string[];
  salary: number | null;
  sort: "recent" | "salary" | "relevance";
  cursor: string | null;
};

export type RawParams = Record<string, string | string[] | undefined>;

const TYPES = ["remote", "hybrid", "onsite"];
const ROLES = Object.keys(ROLE_LABELS);
const SORTS = ["recent", "salary", "relevance"] as const;

function values(raw: string | string[] | undefined): string[] {
  const list = Array.isArray(raw) ? raw : raw ? [raw] : [];
  return list.flatMap((v) => v.split(",")).map((v) => v.trim()).filter(Boolean);
}

export function parseFilters(params: RawParams): Filters {
  const countries = [...new Set(values(params.country).map((c) => c.toUpperCase()))].filter((c) =>
    /^[A-Z]{2}$/.test(c),
  );
  const salary = Number(values(params.salary)[0]);
  const sort = values(params.sort)[0] as Filters["sort"];
  return {
    q: values(params.q).join(" ").slice(0, 200),
    countries,
    ww: values(params.ww)[0] !== "0",
    types: values(params.type).filter((t) => TYPES.includes(t)),
    roles: values(params.role).filter((r) => ROLES.includes(r)),
    salary: Number.isFinite(salary) && salary > 0 ? salary : null,
    sort: SORTS.includes(sort) ? sort : "recent",
    cursor: values(params.cursor)[0] ?? null,
  };
}

/** Canonical query string; ``changes`` override parts of ``filters``. */
export function toQuery(filters: Filters, changes: Partial<Filters> = {}): string {
  const f = { ...filters, cursor: null, ...changes };
  const params = new URLSearchParams();
  if (f.q) params.set("q", f.q);
  if (f.countries.length) params.set("country", f.countries.join(","));
  if (!f.ww) params.set("ww", "0");
  if (f.types.length) params.set("type", f.types.join(","));
  if (f.roles.length) params.set("role", f.roles.join(","));
  if (f.salary) params.set("salary", String(f.salary));
  if (f.sort !== "recent") params.set("sort", f.sort);
  if (f.cursor) params.set("cursor", f.cursor);
  const query = params.toString().replaceAll("%2C", ",");
  return query ? `?${query}` : "";
}

/** Parameters for GET /v1/jobs. */
export function toApiParams(filters: Filters, perPage = 25): Record<string, string | number | boolean | undefined> {
  return {
    q: filters.q || undefined,
    country: filters.countries.join(",") || undefined,
    include_worldwide: filters.countries.length ? filters.ww : undefined,
    remote_status: filters.types.join(",") || undefined,
    role: filters.roles.join(",") || undefined,
    salary_min_usd: filters.salary ?? undefined,
    sort: filters.sort === "relevance" && !filters.q ? "recent" : filters.sort,
    cursor: filters.cursor ?? undefined,
    per_page: perPage,
  };
}
