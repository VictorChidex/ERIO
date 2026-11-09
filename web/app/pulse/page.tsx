import type { Metadata } from "next";
import Link from "next/link";

import { ApiUnavailable, getPulse, type Pulse } from "@/lib/api";
import { ageLabel, formatCount } from "@/lib/format";

import { BarList, FlowChart, PayRanges, Stat, percent } from "./charts";
import styles from "./insights.module.css";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Market pulse",
  description:
    "Live figures from every open role ERIO indexes: what is hiring, where, how fresh, and what employers advertise they pay.",
};

async function load(): Promise<Pulse | null> {
  try {
    return (await getPulse()).data;
  } catch (error) {
    if (error instanceof ApiUnavailable) return null;
    throw error;
  }
}

const WORK_TYPES = new Set(["remote", "hybrid", "onsite"]);

export default async function PulsePage() {
  const pulse = await load();
  return (
    <>
      <div className="page-header">
        <div className="wrap">
          <div className="sect-eye">◉ Market pulse</div>
          <h1 className="page-title">The job market, as it is right now.</h1>
          <p className="page-sub">
            Counted from every open role in the index. Nothing is estimated, and each number opens
            the roles behind it where a search can show them.
          </p>
          {pulse && (
            <div className={styles.stats}>
              <Stat value={formatCount(pulse.totals.open_roles)} label="Open roles" href="/search" />
              <Stat value={formatCount(pulse.totals.companies_hiring)} label="Companies hiring" href="/companies" />
              <Stat value={formatCount(pulse.totals.sources_watched)} label="Job boards watched" href="/coverage" />
              <Stat value={formatCount(pulse.totals.platforms_live)} label="Platforms with open roles" href="/coverage" />
              <Stat value={percent(pulse.totals.pay_stated_pct)} label="Roles stating pay" href="/search?salary=1" />
            </div>
          )}
        </div>
      </div>
      {pulse ? (
        <div className="wrap">
          <section className={styles.section}>
            <h2 className={styles.h2}>Roles added and removed, last 30 days</h2>
            <p className={styles.note}>Each day, how many roles appeared and how many disappeared from employers&apos; boards.</p>
            <div className={styles.card}>
              <FlowChart flow={pulse.flow} />
            </div>
          </section>

          <section className={styles.section}>
            <div className={styles.grid}>
              <div className={styles.card}>
                <h2 className={styles.h2}>How fresh the open roles are</h2>
                <p className={styles.note}>By the date the employer gave.</p>
                <BarList rows={pulse.posted} />
              </div>
              <div className={styles.card}>
                <h2 className={styles.h2}>When we last saw them live</h2>
                <p className={styles.note}>Time since ERIO last confirmed each role on its board.</p>
                <BarList rows={pulse.last_seen} />
              </div>
            </div>
          </section>

          <section className={styles.section}>
            <div className={styles.grid}>
              <div className={styles.card}>
                <h2 className={styles.h2}>What is hiring</h2>
                <p className={styles.note}>Open roles by field.</p>
                <BarList rows={pulse.roles} href={(r) => `/search?role=${r.key}`} />
              </div>
              <div className={styles.card}>
                <h2 className={styles.h2}>How people work</h2>
                <p className={styles.note}>Remote, hybrid or on-site, as each employer states it.</p>
                <BarList rows={pulse.work_mode} href={(r) => (WORK_TYPES.has(r.key) ? `/search?type=${r.key}` : null)} />
              </div>
            </div>
          </section>

          <section className={styles.section}>
            <h2 className={styles.h2}>What employers advertise they pay</h2>
            <p className={styles.note}>
              Yearly pay only. For each currency: the lower quartile, median and upper quartile of
              each range&apos;s midpoint. Amounts stay in the currency they were posted in and are
              never converted. {formatCount(pulse.totals.roles_stating_pay)} open roles state pay
              in some form.
            </p>
            <div className={styles.card}>
              <PayRanges rows={pulse.pay} />
            </div>
          </section>

          <section className={styles.section}>
            <h2 className={styles.h2}>Top countries</h2>
            <p className={styles.note}>Roles located in each country, with the share that are remote and the share that state pay.</p>
            <div className={styles.card}>
              {pulse.countries.length ? (
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Country</th>
                      <th className={styles.num}>Roles</th>
                      <th className={styles.num}>Remote</th>
                      <th className={styles.num}>State pay</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pulse.countries.map((c) => (
                      <tr key={c.code}>
                        <td>
                          <Link href={`/countries/${c.code}`}>{c.name}</Link>
                        </td>
                        <td className={styles.num}>{formatCount(c.roles)}</td>
                        <td className={styles.num}>{percent(c.remote_pct)}</td>
                        <td className={styles.num}>{percent(c.pay_stated_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className={styles.empty}>No located roles yet.</p>
              )}
            </div>
          </section>

          <section className={`${styles.section} ${styles.bottom}`}>
            <h2 className={styles.h2}>Where the roles come from</h2>
            <p className={styles.note}>
              {formatCount(pulse.sources.ats_roles)} roles are read from applicant tracking systems
              and {formatCount(pulse.sources.board_roles)} from job boards. A role found on two
              platforms counts once in each group, and in each platform below.
            </p>
            <div className={styles.card}>
              <BarList
                rows={pulse.sources.platforms.map((p) => ({
                  key: p.slug,
                  label: `${p.name} (${p.kind === "ats" ? "ATS" : "job board"})`,
                  count: p.roles,
                }))}
              />
              <p className={styles.small}>
                Figures refresh every few minutes; these were generated {ageLabel(pulse.generated_at)}.{" "}
                <Link href="/coverage">See platform health</Link>
              </p>
            </div>
          </section>
        </div>
      ) : (
        <div className="wrap">
          <section className={styles.section}>
            <div className="empty" role="alert">
              <h3>The market pulse is unavailable right now</h3>
              <p>The job index could not be reached. Please try again in a minute.</p>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
