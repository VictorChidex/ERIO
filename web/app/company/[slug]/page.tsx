import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { BarList, FlowChart, PayRanges, Stat, percent } from "@/app/pulse/charts";
import styles from "@/app/pulse/insights.module.css";
import { ApiUnavailable, NotFound, getCompany, getCountries, type CompanyProfile } from "@/lib/api";
import { ageLabel, formatCount, ROLE_LABELS, TYPE_LABELS } from "@/lib/format";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ slug: string }> };

async function load(slug: string): Promise<CompanyProfile | null> {
  try {
    return (await getCompany(slug)).data;
  } catch (error) {
    if (error instanceof NotFound) notFound();
    if (error instanceof ApiUnavailable) return null;
    throw error;
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const company = await load((await params).slug);
  if (!company) return { title: "Company" };
  return {
    title: `${company.name}: open roles and hiring`,
    description: `${company.name} has ${company.open_roles} open roles. See what it hires for, where, how its openings change and what it advertises it pays.`,
  };
}

const date = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });

export default async function CompanyPage({ params }: Props) {
  const company = await load((await params).slug);
  if (!company) {
    return (
      <div className="wrap">
        <section className={styles.section}>
          <div className="empty" role="alert">
            <h3>This company page is unavailable right now</h3>
            <p>The job index could not be reached. Please try again in a minute.</p>
          </div>
        </section>
      </div>
    );
  }
  let countryNames: Record<string, string> = {};
  try {
    countryNames = Object.fromEntries((await getCountries()).data.map((c) => [c.code, c.name]));
  } catch {
    // Codes are shown as they are.
  }
  const roles = company.roles.map((r) => ({ ...r, label: ROLE_LABELS[r.key] ?? r.label }));
  const work = company.work_mode.map((r) => ({ ...r, label: TYPE_LABELS[r.key] ?? r.label }));

  return (
    <>
      <div className="page-header">
        <div className="wrap">
          <div className="sect-eye">◉ Company</div>
          <h1 className="page-title">{company.name}</h1>
          <p className="page-sub">
            Tracked since {date(company.tracked_since)}
            {company.last_checked_at ? `, last checked ${ageLabel(company.last_checked_at)}` : ""}.
            {company.domain && (
              <>
                {" "}
                <a href={`https://${company.domain}`} rel="noopener noreferrer nofollow" target="_blank">
                  {company.domain}
                </a>
              </>
            )}
          </p>
          <div className={styles.stats}>
            <Stat value={formatCount(company.open_roles)} label="Open roles" href="#openings" />
            <Stat value={`+${formatCount(company.added_30d)}`} label="Added in 30 days" />
            <Stat value={`−${formatCount(company.removed_30d)}`} label="Removed in 30 days" />
            <Stat value={percent(company.remote_pct)} label="Remote" />
            <Stat value={percent(company.pay_stated_pct)} label="State pay" />
          </div>
        </div>
      </div>
      <div className="wrap">
        <section className={styles.section}>
          <h2 className={styles.h2}>Postings added and removed</h2>
          <p className={styles.note}>The last 30 days.</p>
          <div className={styles.card}>
            <FlowChart flow={company.flow} />
          </div>
        </section>

        <section className={styles.section}>
          <div className={styles.grid}>
            <div className={styles.card}>
              <h2 className={styles.h2}>What it hires for</h2>
              <BarList rows={roles} href={(r) => `/search?role=${r.key}`} />
            </div>
            <div className={styles.card}>
              <h2 className={styles.h2}>Where the roles are</h2>
              <BarList rows={company.countries.map((c) => ({ ...c, label: countryNames[c.key] ?? c.label }))} href={(r) => `/countries/${r.key}`} />
              {company.locations.length > 0 && (
                <>
                  <p className={styles.small}>Busiest locations</p>
                  <BarList rows={company.locations} />
                </>
              )}
            </div>
          </div>
        </section>

        <section className={styles.section}>
          <div className={styles.grid}>
            <div className={styles.card}>
              <h2 className={styles.h2}>Work mode</h2>
              <BarList rows={work} />
            </div>
            <div className={styles.card}>
              <h2 className={styles.h2}>Contract mix</h2>
              <BarList rows={company.contracts} />
            </div>
            <div className={styles.card}>
              <h2 className={styles.h2}>Freshness</h2>
              <BarList rows={company.posted} />
            </div>
          </div>
        </section>

        <section className={styles.section}>
          <h2 className={styles.h2}>What it advertises it pays</h2>
          <p className={styles.note}>
            Lower quartile, median and upper quartile of each posted range&apos;s midpoint, kept
            apart by currency and by period. Nothing is converted.
          </p>
          <div className={styles.card}>
            <PayRanges rows={company.pay} />
          </div>
        </section>

        <section className={styles.section}>
          <div className={styles.grid}>
            <div className={styles.card}>
              <h2 className={styles.h2}>Where we find them</h2>
              <BarList
                rows={company.platforms.map((p) => ({
                  key: p.slug,
                  label: `${p.name} (${p.kind === "ats" ? "ATS" : "job board"})`,
                  count: p.roles,
                }))}
              />
            </div>
          </div>
        </section>

        <section className={`${styles.section} ${styles.bottom}`} id="openings">
          <h2 className={styles.h2}>Latest openings</h2>
          {company.latest.length ? (
            <ul className={styles.openings}>
              {company.latest.map((job) => (
                <li className={styles.opening} key={job.canonical_id}>
                  <Link href={`/jobs/${job.canonical_id}`}>{job.title}</Link>
                  <span className={styles.openingMeta}>
                    {[
                      job.location_text ?? (job.country_code ? countryNames[job.country_code] : null),
                      TYPE_LABELS[job.remote_status],
                      ageLabel(job.posted_at ?? job.indexed_at),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.empty}>No open roles right now.</p>
          )}
          <p className={styles.small}>
            <Link href="/companies">All companies</Link>
          </p>
        </section>
      </div>
    </>
  );
}
