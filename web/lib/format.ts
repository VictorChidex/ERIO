// Display helpers. Salaries show in the currency and period the employer
// posted; the USD value is only used for filtering (spec section 6).

import type { JobRecord } from "./api";

const SYMBOLS: Record<string, string> = {
  USD: "$", EUR: "€", GBP: "£", NGN: "₦", INR: "₹", JPY: "¥", KRW: "₩", PHP: "₱",
  CAD: "C$", AUD: "A$", NZD: "NZ$", SGD: "S$", HKD: "HK$", BRL: "R$", MXN: "MX$",
  ILS: "₪", TRY: "₺", KES: "KSh ", GHS: "GH₵", ZAR: "R ",
};

const PERIOD_SUFFIX: Record<string, string> = { year: "", month: "/mo", hour: "/hr" };

export const ROLE_LABELS: Record<string, string> = {
  engineering: "Engineering",
  product: "Product",
  design: "Design",
  data: "Data & ML",
  operations: "Operations",
  sales: "Sales",
  marketing: "Marketing",
  healthcare: "Healthcare",
  education: "Education",
  hospitality: "Hospitality & food",
  retail: "Retail",
  logistics: "Logistics & drivers",
  trades: "Trades & production",
  security: "Security",
  other: "Other",
};

export const TYPE_LABELS: Record<string, string> = {
  remote: "Remote",
  hybrid: "Hybrid",
  onsite: "On-site",
};

export const SOURCE_LABELS: Record<string, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  smartrecruiters: "SmartRecruiters",
  recruitee: "Recruitee",
  workable: "Workable",
};

function compact(amount: number, period: string | null): string {
  if (period === "hour") return amount % 1 ? amount.toFixed(2) : String(amount);
  if (amount >= 1_000_000) return `${+(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000) return `${Math.round(amount / 1_000)}k`;
  return String(amount);
}

export function salaryLabel(job: Pick<JobRecord, "salary_min" | "salary_max" | "salary_currency" | "salary_period">): string | null {
  const { salary_min: min, salary_max: max, salary_currency: currency, salary_period: period } = job;
  if (min === null && max === null) return null;
  const symbol = currency ? (SYMBOLS[currency] ?? `${currency} `) : "";
  const suffix = PERIOD_SUFFIX[period ?? "year"] ?? "";
  const low = min ?? max ?? 0;
  const high = max ?? min ?? 0;
  const range = low === high ? `${symbol}${compact(low, period)}` : `${symbol}${compact(low, period)}–${symbol}${compact(high, period)}`;
  return `${range}${suffix}`;
}

export function locationLabel(job: Pick<JobRecord, "location_text" | "city" | "country_code" | "remote_scope">, countryNames: Record<string, string>): string {
  if (job.remote_scope === "worldwide") return "Remote · worldwide";
  if (job.location_text) return job.location_text;
  const country = job.country_code ? (countryNames[job.country_code] ?? job.country_code) : null;
  return [job.city, country].filter(Boolean).join(", ") || "Location not stated";
}

export function ageLabel(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "recently";
  const minutes = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 60_000);
  if (minutes < 60) return `${Math.max(1, Math.round(minutes))}m ago`;
  const hours = minutes / 60;
  if (hours < 48) return `${Math.round(hours)}h ago`;
  const days = hours / 24;
  if (days < 60) return `${Math.round(days)}d ago`;
  return `${Math.round(days / 30)}mo ago`;
}

/**
 * Freshness at a glance: whether the job was posted in the last day, and how
 * long ago its source was last read. Both come straight from the record.
 */
export function freshness(
  job: Pick<JobRecord, "posted_at" | "last_verified_at">,
  now: Date = new Date(),
): { isNew: boolean; checked: string | null } {
  const hours = job.posted_at ? (now.getTime() - new Date(job.posted_at).getTime()) / 3_600_000 : null;
  return {
    isNew: hours !== null && hours < 24,
    checked: job.last_verified_at ? `Checked ${ageLabel(job.last_verified_at, now)}` : null,
  };
}

export function sourceLabel(sources: string[]): string {
  return sources.map((s) => SOURCE_LABELS[s] ?? s).join(", ") || "source";
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}
