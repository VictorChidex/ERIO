import type { Metadata } from "next";
import Link from "next/link";

import { money } from "@/app/pulse/charts";
import styles from "@/app/pulse/insights.module.css";
import { ApiUnavailable, getCountries, getSalary, NotFound, type PayCell, type SalaryExplorer } from "@/lib/api";
import { formatCount, ROLE_LABELS } from "@/lib/format";
import { jobsBehind } from "@/lib/pay";
import { absoluteUrl, breadcrumbJsonLd, scriptJson } from "@/lib/seo";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Pay explorer",
  description:
    "What employers advertise they pay, by role and country: yearly pay quartiles in the currency each job was posted in, never converted, with the number of jobs behind every figure.",
  alternates: { canonical: absoluteUrl("/salary") },
};

type Search = { role?: string; country?: string };

async function load(search: Search): Promise<SalaryExplorer | null> {
  try {
    return (
      await getSalary({
        role: search.role && search.role in ROLE_LABELS ? search.role : undefined,
        country: /^[A-Za-z]{2}$/.test(search.country ?? "") ? search.country : undefined,
      })
    ).data;
  } catch (error) {
    // An API without this endpoint (not yet redeployed) answers 404: shown as unavailable.
    if (error instanceof ApiUnavailable || error instanceof NotFound) return null;
    throw error;
  }
}

function Table({
  rows,
  show,
  names,
}: {
  rows: PayCell[];
  show: ("role" | "country")[];
  names: Record<string, string>;
}) {
  if (!rows.length) return <p className={styles.empty}>No group has enough jobs stating pay to show a figure.</p>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table className={styles.table}>
        <thead>
          <tr>
            {show.includes("role") && <th>Role</th>}
            {show.includes("country") && <th>Country</th>}
            <th>Currency</th>
            <th className={styles.num}>Jobs</th>
            <th className={styles.num}>Lower</th>
            <th className={styles.num}>Median</th>
            <th className={styles.num}>Upper</th>
            <th>Jobs behind it</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.role}-${row.country}-${row.currency}`}>
              {show.includes("role") && <td>{ROLE_LABELS[row.role ?? ""] ?? row.role}</td>}
              {show.includes("country") && <td>{row.country ? (names[row.country] ?? row.country) : ""}</td>}
              <td>{row.currency}</td>
              <td className={styles.num}>{formatCount(row.roles)}</td>
              <td className={styles.num}>{money(row.lower, row.currency)}</td>
              <td className={styles.num}>{money(row.median, row.currency)}</td>
              <td className={styles.num}>{money(row.upper, row.currency)}</td>
              <td>
                <Link href={jobsBehind(row)}>See the jobs</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function SalaryPage({ searchParams }: { searchParams: Promise<Search> }) {
  const search = await searchParams;
  const data = await load(search);
  const countries = await getCountries()
    .then((c) => c.data)
    .catch(() => []);
  const names = Object.fromEntries(countries.map((c) => [c.code, c.name]));
  const choices = countries.filter((c) => c.job_count > 0).sort((a, b) => a.name.localeCompare(b.name));
  const trail = [
    { name: "ERIO", path: "/" },
    { name: "Pay explorer", path: "/salary" },
  ];
  const narrowed = Boolean(data?.role || data?.country);

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: scriptJson(breadcrumbJsonLd(trail)) }} />
      <div className="page-header">
        <div className="wrap">
          <div className="sect-eye">◉ Pay explorer</div>
          <h1 className="page-title">What jobs advertise they pay.</h1>
          <p className="page-sub">
            Yearly pay that employers wrote in their postings, by role and country. Each figure is the
            lower quartile, median and upper quartile of the advertised ranges&apos; midpoints, in the
            currency the job was posted in. Currencies are never converted, and a figure appears only
            when at least {data?.min_sample ?? 10} jobs state pay for it.
          </p>
          <form className={styles.search} action="/salary" role="search">
            <select className={styles.input} name="role" defaultValue={data?.role ?? ""} aria-label="Role">
              <option value="">Every role</option>
              {Object.entries(ROLE_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
            <select className={styles.input} name="country" defaultValue={data?.country ?? ""} aria-label="Country">
              <option value="">Every country</option>
              {choices.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </select>
            <button className={styles.button} type="submit">
              Show pay
            </button>
            {narrowed && (
              <Link className="btn-ghost" href="/salary">
                Clear
              </Link>
            )}
          </form>
        </div>
      </div>
      <div className="wrap">
        {data ? (
          <>
            {!narrowed && (
              <>
                <section className={styles.section}>
                  <h2 className={styles.h2}>By role</h2>
                  <p className={styles.note}>All countries, per currency. Jobs with no country (worldwide remote) are included here.</p>
                  <div className={styles.card}>
                    <Table rows={data.by_role} show={["role"]} names={names} />
                  </div>
                </section>
                <section className={styles.section}>
                  <h2 className={styles.h2}>By country</h2>
                  <p className={styles.note}>All roles, per currency, for the country the job is based in.</p>
                  <div className={styles.card}>
                    <Table rows={data.by_country} show={["country"]} names={names} />
                  </div>
                </section>
              </>
            )}
            <section className={styles.section}>
              <h2 className={styles.h2}>{narrowed ? "Pay for this selection" : "Role and country together"}</h2>
              <p className={styles.note}>
                {narrowed
                  ? "Every role, country and currency combination with enough jobs."
                  : "The largest role and country combinations."}{" "}
                {data.hidden_cells > 0 &&
                  `${formatCount(data.hidden_cells)} combination${data.hidden_cells === 1 ? " has" : "s have"} fewer than ${data.min_sample} jobs stating pay and ${data.hidden_cells === 1 ? "is" : "are"} left out.`}
              </p>
              <div className={styles.card}>
                <Table rows={data.cells.slice(0, narrowed ? 200 : 60)} show={["role", "country"]} names={names} />
              </div>
              <p className={styles.small}>
                Only postings that state a yearly range count; monthly and hourly pay is not scaled up to a
                year. The jobs link opens roles in that role and country with pay stated, highest first; it
                includes every currency, so its list can be longer than the number shown here.
              </p>
            </section>
          </>
        ) : (
          <section className={styles.section}>
            <div className="empty" role="alert">
              <h3>The pay explorer is unavailable right now</h3>
              <p>The job index could not be reached. Please try again in a minute.</p>
            </div>
          </section>
        )}
      </div>
    </>
  );
}
