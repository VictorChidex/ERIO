// Atom feeds of searches, so a feed reader can follow one. Pure: the route
// handler fetches the jobs and this turns them into XML.

import type { JobRecord } from "./api";
import { locationLabel, salaryLabel, TYPE_LABELS } from "./format";
import { absoluteUrl, xmlEscape } from "./seo";

export type FeedJob = Pick<
  JobRecord,
  | "canonical_id"
  | "title"
  | "company"
  | "location_text"
  | "city"
  | "country_code"
  | "remote_scope"
  | "remote_status"
  | "posted_at"
  | "indexed_at"
  | "salary_min"
  | "salary_max"
  | "salary_currency"
  | "salary_period"
>;

export const FEED_SIZE = 50;

/** One line about a job: where, how, and pay when the employer gave it. */
export function feedSummary(job: FeedJob, countryNames: Record<string, string>): string {
  const pay = salaryLabel(job);
  return [locationLabel(job, countryNames), TYPE_LABELS[job.remote_status], pay].filter(Boolean).join(" · ");
}

/** Atom 1.0 for ``jobs`` (newest first). ``selfPath`` is this feed's own address, query included. */
export function atomFeed(options: {
  title: string;
  selfPath: string;
  jobs: FeedJob[];
  countryNames: Record<string, string>;
  now?: Date;
}): string {
  const { title, selfPath, jobs, countryNames } = options;
  const stamp = (iso: string | null | undefined) => new Date(iso ?? options.now ?? Date.now()).toISOString();
  const updated = jobs.length ? stamp(jobs[0]?.posted_at ?? jobs[0]?.indexed_at) : stamp(null);
  const entries = jobs.slice(0, FEED_SIZE).map((job) => {
    const link = absoluteUrl(`/jobs/${job.canonical_id}`);
    return [
      "<entry>",
      `<id>urn:erio:job:${xmlEscape(job.canonical_id)}</id>`,
      `<title>${xmlEscape(`${job.title} at ${job.company.name}`)}</title>`,
      `<link rel="alternate" type="text/html" href="${xmlEscape(link)}"/>`,
      `<updated>${stamp(job.posted_at ?? job.indexed_at)}</updated>`,
      `<summary>${xmlEscape(feedSummary(job, countryNames))}</summary>`,
      "</entry>",
    ].join("");
  });
  return `<?xml version="1.0" encoding="UTF-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom"><id>${xmlEscape(absoluteUrl(selfPath))}</id><title>${xmlEscape(title)}</title><updated>${updated}</updated><link rel="self" type="application/atom+xml" href="${xmlEscape(absoluteUrl(selfPath))}"/><link rel="alternate" type="text/html" href="${xmlEscape(absoluteUrl("/search"))}"/><generator>ERIO</generator>\n${entries.join("\n")}\n</feed>\n`;
}
