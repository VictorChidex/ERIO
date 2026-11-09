// A job's history as readable lines ("Pay changed from $90k to $100k").
// Pure, so the unit tests can run it. The API sends `history` newest first and
// only on newer versions of GET /v1/jobs/{id}; every caller treats it as optional.

import type { JobRecord } from "./api";
import { salaryLabel } from "./format";

export type HistoryKind = "added" | "changed" | "closed" | "reopened" | "merged";

export type HistoryEvent = {
  at: string;
  kind: HistoryKind;
  /** field -> [old value, new value] */
  changes?: Record<string, [unknown, unknown]> | null;
};

const PAY_FIELDS = ["salary_min", "salary_max", "salary_currency", "salary_period"] as const;
const PLACE_FIELDS = ["location_text", "city", "region", "country_code"] as const;

const FIELD_NAMES: Record<string, string> = {
  title: "Title",
  role_category: "Role category",
  remote_status: "Work mode",
  remote_scope: "Remote scope",
  employment_type: "Contract type",
  apply_url: "Apply link",
  status: "Status",
};

const KIND_TEXT: Record<Exclude<HistoryKind, "changed">, string> = {
  added: "First seen by ERIO",
  closed: "Closed: the employer's page no longer lists it",
  reopened: "Reopened: listed again by the employer",
  merged: "Merged with a duplicate listing of the same job",
};

const shown = (value: unknown): string =>
  value === null || value === undefined || value === "" ? "not stated" : String(value).replace(/_/g, " ");

const humanize = (field: string): string => {
  const words = field.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
};

type PayFields = Pick<JobRecord, "salary_min" | "salary_max" | "salary_currency" | "salary_period">;

/**
 * One line per change in the event. Fields the event leaves unchanged keep the
 * job's current value, so a currency-only change still prints whole pay ranges.
 */
export function describeEvent(event: HistoryEvent, job: PayFields): string[] {
  if (event.kind !== "changed") return [KIND_TEXT[event.kind]];
  const changes = event.changes ?? {};
  const lines: string[] = [];
  if (PAY_FIELDS.some((field) => field in changes)) {
    const side = (index: 0 | 1): PayFields => {
      const pay: PayFields = { ...job };
      for (const field of PAY_FIELDS) {
        const pair = changes[field];
        if (pair) (pay as Record<string, unknown>)[field] = pair[index];
      }
      return pay;
    };
    const before = salaryLabel(side(0));
    const after = salaryLabel(side(1));
    lines.push(
      before && after
        ? `Pay changed from ${before} to ${after}`
        : after
          ? `Pay added: ${after}`
          : before
            ? `Pay removed (was ${before})`
            : "Pay details changed",
    );
  }
  const place = PLACE_FIELDS.filter((field) => field in changes);
  if (place.length > 0) {
    const text = (index: 0 | 1) =>
      PLACE_FIELDS.map((field) => (changes[field] ? changes[field][index] : null))
        .filter((part) => part !== null && part !== undefined && part !== "")
        .join(", ");
    lines.push(
      text(0) && text(1) ? `Location changed from ${text(0)} to ${text(1)}` : `Location changed to ${text(1) || "not stated"}`,
    );
  }
  for (const [field, pair] of Object.entries(changes)) {
    if ((PAY_FIELDS as readonly string[]).includes(field) || (PLACE_FIELDS as readonly string[]).includes(field)) continue;
    if (!Array.isArray(pair) || pair.length !== 2) continue;
    if (field === "description_text" || field === "description_html") {
      lines.push("Description updated");
      continue;
    }
    lines.push(`${FIELD_NAMES[field] ?? humanize(field)} changed from ${shown(pair[0])} to ${shown(pair[1])}`);
  }
  return lines.length > 0 ? lines : ["Details changed"];
}

/** The events worth showing, oldest last, as received; anything malformed is dropped. */
export function usableHistory(history: unknown): HistoryEvent[] {
  if (!Array.isArray(history)) return [];
  const kinds = new Set<string>(["added", "changed", "closed", "reopened", "merged"]);
  return history.filter(
    (event): event is HistoryEvent =>
      typeof event === "object" &&
      event !== null &&
      typeof (event as HistoryEvent).at === "string" &&
      kinds.has((event as HistoryEvent).kind),
  );
}
