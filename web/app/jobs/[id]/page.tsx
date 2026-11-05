import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { getCountries, getJob, type JobRecord, NotFound } from "@/lib/api";
import { ageLabel, locationLabel, ROLE_LABELS, salaryLabel, sourceLabel, TYPE_LABELS } from "@/lib/format";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

async function load(id: string): Promise<JobRecord> {
  try {
    return (await getJob(id)).data;
  } catch (error) {
    if (error instanceof NotFound) notFound();
    throw error;
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const job = await load((await params).id);
  return {
    title: `${job.title} at ${job.company.name}`,
    description: job.description_text?.slice(0, 160) ?? `${job.title} at ${job.company.name}`,
  };
}

const PERIOD_UNIT: Record<string, string> = { year: "YEAR", month: "MONTH", hour: "HOUR" };

/** schema.org JobPosting for Google Jobs (spec section 8). */
function jobPosting(job: JobRecord): Record<string, unknown> {
  const posting: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    title: job.title,
    description: job.description_html ?? job.description_text ?? job.title,
    identifier: { "@type": "PropertyValue", name: "ERIO", value: job.canonical_id },
    datePosted: job.posted_at ?? job.indexed_at,
    directApply: false,
    hiringOrganization: {
      "@type": "Organization",
      name: job.company.name,
      ...(job.company.domain ? { sameAs: `https://${job.company.domain}` } : {}),
    },
  };
  if (job.remote_status === "remote") {
    posting.jobLocationType = "TELECOMMUTE";
    const countries = job.eligible_country_codes.length ? job.eligible_country_codes : [];
    if (countries.length) {
      posting.applicantLocationRequirements = countries.map((code) => ({ "@type": "Country", name: code }));
    }
  }
  if (job.country_code) {
    posting.jobLocation = {
      "@type": "Place",
      address: {
        "@type": "PostalAddress",
        addressCountry: job.country_code,
        ...(job.city ? { addressLocality: job.city } : {}),
        ...(job.region ? { addressRegion: job.region } : {}),
      },
    };
  }
  if (job.salary_currency && (job.salary_min || job.salary_max)) {
    posting.baseSalary = {
      "@type": "MonetaryAmount",
      currency: job.salary_currency,
      value: {
        "@type": "QuantitativeValue",
        ...(job.salary_min ? { minValue: job.salary_min } : {}),
        ...(job.salary_max ? { maxValue: job.salary_max } : {}),
        unitText: PERIOD_UNIT[job.salary_period ?? "year"],
      },
    };
  }
  return posting;
}

/** JSON for a <script> tag: "<" escaped so text in a job can never close the tag. */
function scriptJson(value: unknown): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

export default async function JobPage({ params }: Props) {
  const job = await load((await params).id);
  const countries = await getCountries().catch(() => ({ data: [] }));
  const countryNames = Object.fromEntries(countries.data.map((c) => [c.code, c.name]));
  const salary = salaryLabel(job);
  const eligible = job.eligible_country_codes.map((code) => countryNames[code] ?? code);

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: scriptJson(jobPosting(job)) }} />
      <div className="page-header">
        <div className="wrap">
          <nav className="jd-crumbs" aria-label="Breadcrumb">
            <Link href="/search">Search</Link>
            {job.country_code && (
              <>
                {" / "}
                <Link href={`/countries/${job.country_code.toLowerCase()}`}>
                  {countryNames[job.country_code] ?? job.country_code}
                </Link>
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
              Apply on {sourceLabel(job.sources.slice(0, 1))} ↗
            </a>
            <Link className="btn-ghost" href={`/search?q=${encodeURIComponent(job.company.name)}`}>
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
            {job.sources.length > 1 && (
              <p className="jd-also">Also posted on {sourceLabel(job.sources.slice(1))}.</p>
            )}
            <p className="jd-verify">
              {job.last_verified_at
                ? `Last confirmed open by its source ${ageLabel(job.last_verified_at)}.`
                : "Not yet confirmed by its source."}
            </p>
          </article>
        </div>
      </section>
    </>
  );
}
