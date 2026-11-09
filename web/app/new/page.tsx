import type { Metadata } from "next";
import Link from "next/link";

import styles from "@/app/pulse/insights.module.css";
import { JobCard } from "@/components/JobCard";
import { ApiUnavailable, getCountries, type JobsPage, searchJobs } from "@/lib/api";
import { formatCount, ROLE_LABELS } from "@/lib/format";
import { absoluteUrl, breadcrumbJsonLd, scriptJson } from "@/lib/seo";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "What's new today",
  description: "Jobs posted in the last 24 hours, by country and kind of work, with a feed you can follow.",
  alternates: { canonical: absoluteUrl("/new") },
};

type Search = { country?: string; role?: string };

const DAY_MS = 24 * 3_600_000;

/** Query string for /new and /feed.xml, keeping only the filters that are set. */
function query(country: string | undefined, role: string | undefined, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams(extra);
  if (country) params.set("country", country);
  if (role) params.set("role", role);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export default async function NewPage({ searchParams }: { searchParams: Promise<Search> }) {
  const raw = await searchParams;
  const country = /^[A-Za-z]{2}$/.test(raw.country ?? "") ? (raw.country as string).toUpperCase() : undefined;
  const role = raw.role && raw.role in ROLE_LABELS ? raw.role : undefined;
  let page: JobsPage | null = null;
  try {
    page = await searchJobs({
      posted_after: new Date(Date.now() - DAY_MS).toISOString(),
      country,
      include_worldwide: country ? false : undefined,
      role,
      sort: "recent",
      per_page: 25,
    });
  } catch (error) {
    if (!(error instanceof ApiUnavailable)) throw error;
  }
  const countries = await getCountries()
    .then((c) => c.data)
    .catch(() => []);
  const names = Object.fromEntries(countries.map((c) => [c.code, c.name]));
  const trail = [
    { name: "ERIO", path: "/" },
    { name: "What's new", path: "/new" },
  ];
  const facets = page?.meta.facets;
  const byCountry = Object.entries(facets?.country ?? {})
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 15);
  const byRole = Object.entries(facets?.role ?? {}).sort((a, b) => b[1] - a[1]);
  const total = page?.meta.total ?? 0;

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: scriptJson(breadcrumbJsonLd(trail)) }} />
      <div className="page-header">
        <div className="wrap">
          <div className="sect-eye">◉ What&apos;s new</div>
          <h1 className="page-title">Posted in the last 24 hours.</h1>
          <p className="page-sub">
            {page
              ? `${formatCount(total)} ${total === 1 ? "job was" : "jobs were"} posted in the last day${country ? ` in ${names[country] ?? country}` : ""}${role ? ` in ${ROLE_LABELS[role]}` : ""}. Jobs whose employer gave no posted date are not counted here.`
              : "The job index could not be reached. Please try again in a minute."}
          </p>
          <div className="hero-actions">
            <a className="btn-acc" href={`/feed.xml${query(country, role, { new: "1" })}`}>
              Follow this in a feed reader
            </a>
            {(country || role) && (
              <Link className="btn-ghost" href="/new">
                Clear filters
              </Link>
            )}
          </div>
        </div>
      </div>
      <div className="wrap">
        {page && page.data.length > 0 ? (
          <>
            <section className={styles.section}>
              <div className={styles.grid}>
                <div className={styles.card}>
                  <h2 className={styles.h2}>By country</h2>
                  <p className={styles.note}>Where the new jobs are based, or open to.</p>
                  <ul className={styles.bars}>
                    {byCountry.map(([code, count]) => (
                      <li className={styles.bar} key={code}>
                        <span className={styles.barName}>
                          <Link href={`/new${query(code, role)}`}>{names[code] ?? code}</Link>
                        </span>
                        <span />
                        <span className={styles.barNum}>{formatCount(count)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className={styles.card}>
                  <h2 className={styles.h2}>By kind of work</h2>
                  <p className={styles.note}>The same new jobs, by field.</p>
                  <ul className={styles.bars}>
                    {byRole.map(([key, count]) => (
                      <li className={styles.bar} key={key}>
                        <span className={styles.barName}>
                          <Link href={`/new${query(country, key)}`}>{ROLE_LABELS[key] ?? key}</Link>
                        </span>
                        <span />
                        <span className={styles.barNum}>{formatCount(count)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </section>
            <section className={styles.section} style={{ paddingBottom: 64 }}>
              <h2 className={styles.h2}>Latest</h2>
              <div className="jg" role="list" aria-label="Jobs posted in the last 24 hours">
                {page.data.map((job) => (
                  <JobCard key={job.canonical_id} job={job} countryNames={names} />
                ))}
              </div>
              {page.meta.next_cursor && (
                <p className={styles.small}>
                  Showing the latest {page.data.length} of {formatCount(total)}.{" "}
                  <Link href={`/search${query(country, role, { sort: "recent" })}`}>Search all jobs</Link>
                </p>
              )}
            </section>
          </>
        ) : (
          page && (
            <section className={styles.section}>
              <div className="empty">
                <h3>Nothing new matches</h3>
                <p>No job with this filter was posted in the last day. Try another country or field.</p>
              </div>
            </section>
          )
        )}
      </div>
    </>
  );
}
