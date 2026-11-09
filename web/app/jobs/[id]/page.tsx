import type { Metadata } from "next";
import Link from "next/link";
import { notFound, permanentRedirect } from "next/navigation";
import { cache } from "react";

import styles from "@/components/LandingPage.module.css";
import { getCountries, NotFound, searchJobs } from "@/lib/api";
import { ageLabel, locationLabel, ROLE_LABELS, salaryLabel, SOURCE_LABELS, sourceLabel, TYPE_LABELS } from "@/lib/format";
import {
  absoluteUrl,
  breadcrumbJsonLd,
  companyHref,
  countrySlugs,
  jobPageTitle,
  scriptJson,
  snippet,
} from "@/lib/seo";
import { getJobDetail, type JobDetail } from "@/lib/seo-data";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

// Read once per request: generateMetadata and the page share the result.
const load = cache(async (id: string): Promise<JobDetail> => {
  let job: JobDetail;
  try {
    job = (await getJobDetail(id)).data;
    // An API older than source_details simply has no provenance rows to show.
    job.source_details ??= [];
  } catch (error) {
    if (error instanceof NotFound) notFound();
    throw error;
  }
  // A job merged into another (dedup) lives on under the survivor's ID.
  if (job.canonical_id !== id) permanentRedirect(`/jobs/${job.canonical_id}`);
  return job;
});

const loadCountries = cache(async () => {
  const countries = await getCountries().catch(() => ({ data: [] }));
  return { list: countries.data, names: Object.fromEntries(countries.data.map((c) => [c.code, c.name])) };
});

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const job = await load((await params).id);
  const { names } = await loadCountries();
  const title = jobPageTitle(job, names);
  return {
    title,
    description: snippet(job.description_text, title),
    alternates: { canonical: absoluteUrl(`/jobs/${job.canonical_id}`) },
    robots: { index: true, follow: true },
  };
}

// Deliberately no schema.org JobPosting markup. Google's JobPosting rules
// expect the page to be where people apply; here people apply on the
// employer's own page, so claiming the posting would be misleading and could
// cost the site its structured-data standing. Search engines get the title,
// description and BreadcrumbList instead.

const SOURCE_STATUS: Record<string, string> = {
  open: "Listed",
  missing: "Not in the latest check",
  closed: "Closed at source",
};

const day = (iso: string): string => iso.slice(0, 10);

export default async function JobPage({ params }: Props) {
  const job = await load((await params).id);
  const { list, names: countryNames } = await loadCountries();
  const salary = salaryLabel(job);
  const eligible = job.eligible_country_codes.map((code) => countryNames[code] ?? code);
  const slugs = countrySlugs(list);
  const countryName = job.country_code ? (countryNames[job.country_code] ?? job.country_code) : null;
  const countryPath = job.country_code && slugs.has(job.country_code) ? `/jobs/in/${slugs.get(job.country_code)}` : null;

  const trail = [
    { name: "ERIO", path: "/" },
    ...(countryName && countryPath ? [{ name: `Jobs in ${countryName}`, path: countryPath }] : []),
    { name: job.title, path: `/jobs/${job.canonical_id}` },
  ];

  const more = await searchJobs({ company: job.company.name, per_page: 7, sort: "recent" })
    .then((page) => page.data.filter((other) => other.canonical_id !== job.canonical_id).slice(0, 6))
    .catch(() => []);

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: scriptJson(breadcrumbJsonLd(trail)) }} />
      <div className="page-header">
        <div className="wrap">
          <nav className="jd-crumbs" aria-label="Breadcrumb">
            <Link href="/">Home</Link>
            {countryName && countryPath && (
              <>
                {" / "}
                <Link href={countryPath}>Jobs in {countryName}</Link>
              </>
            )}
          </nav>
          <div className="jco jd-company">{job.company.name}</div>
          <h1 className="page-title jd-title">{job.title}</h1>
          <div className="jd-badges">
            <span className={`b ${job.remote_status === "remote" ? "b-grn" : job.remote_status === "hybrid" ? "b-amb" : "b-fg"}`}>
              {TYPE_LABELS[job.remote_status]}
            </span>
            <span className="b b-fg">{ROLE_LABELS[job.role_category] ?? job.role_category}</span>
            {job.status === "open" ? (
              <span className="b b-grn">◉ Verified open</span>
            ) : job.status === "closed" ? (
              <span className="b b-red">Closed</span>
            ) : (
              <span className="b b-amb">Not verified for 72 hours</span>
            )}
          </div>
          <dl className="jd-facts">
            <div>
              <dt>Location</dt>
              <dd>{locationLabel(job, countryNames)}</dd>
            </div>
            {job.remote_status === "remote" && (
              <div>
                <dt>Open to</dt>
                <dd>{job.remote_scope === "worldwide" ? "Applicants anywhere" : eligible.join(", ")}</dd>
              </div>
            )}
            {salary && (
              <div>
                <dt>Salary</dt>
                <dd>{salary} <span className="jd-note">as posted</span></dd>
              </div>
            )}
            <div>
              <dt>Posted</dt>
              <dd>{ageLabel(job.posted_at)}</dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>{sourceLabel(job.sources)}</dd>
            </div>
          </dl>
          <div className="hero-actions">
            <a className="btn-acc" href={job.apply_url} rel="noopener noreferrer nofollow" target="_blank">
              Apply on original site ↗
            </a>
            <Link className="btn-ghost" href={companyHref(job.company.name)}>
              More at {job.company.name}
            </Link>
          </div>
        </div>
      </div>
      <section>
        <div className="wrap">
          <article className="jd-body">
            {job.description_html ? (
              // Sanitized to an allow-list of tags at ingest (spec section 9).
              <div className="jd-desc" dangerouslySetInnerHTML={{ __html: job.description_html }} />
            ) : (
              <p className="jd-desc">{job.description_text ?? "The source did not publish a description."}</p>
            )}
            <p className="jd-verify">
              {job.last_verified_at
                ? `Last confirmed open by its source ${ageLabel(job.last_verified_at)}.`
                : "Not yet confirmed by its source."}
            </p>
          </article>

          {job.source_details.length > 0 && (
            <>
              <h2 className={styles.h2}>Sources</h2>
              <div className={styles.tableWrap}>
                <table className={styles.sources}>
                  <thead>
                    <tr>
                      <th scope="col">Platform</th>
                      <th scope="col">Listing</th>
                      <th scope="col">First seen</th>
                      <th scope="col">Last checked</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {job.source_details.map((source) => (
                      <tr key={`${source.platform}-${source.board_token}-${source.listing_id}`}>
                        <td>{SOURCE_LABELS[source.platform] ?? source.platform}</td>
                        <td>
                          {source.board_token} · {source.listing_id}
                        </td>
                        <td>
                          <time dateTime={source.first_seen_at}>{day(source.first_seen_at)}</time>
                        </td>
                        <td>
                          <time dateTime={source.last_checked_at}>{ageLabel(source.last_checked_at)}</time>
                        </td>
                        <td>{SOURCE_STATUS[source.status] ?? source.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {more.length > 0 && (
            <>
              <h2 className={styles.h2}>More jobs at {job.company.name}</h2>
              <ul className={styles.more}>
                {more.map((other) => (
                  <li key={other.canonical_id}>
                    <Link href={`/jobs/${other.canonical_id}`}>{other.title}</Link>
                    <span className="jd-note"> · {locationLabel(other, countryNames)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </section>
    </>
  );
}
