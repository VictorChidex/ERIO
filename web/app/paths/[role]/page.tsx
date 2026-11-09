import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { BarList, FlowChart, PayRanges, Stat, percent } from "@/app/pulse/charts";
import styles from "@/app/pulse/insights.module.css";
import { ApiUnavailable, getCountries, getRoleInsight, NotFound, type RoleInsight } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { type PathPage, relatedPaths, resolvePath, STARTER_NOTES } from "@/lib/paths";
import {
  absoluteUrl,
  breadcrumbJsonLd,
  companyHref,
  countrySlugs,
  landingPath,
  robotsFor,
  scriptJson,
} from "@/lib/seo";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ role: string }> };

async function load(page: PathPage): Promise<RoleInsight | null> {
  try {
    return (await (page.kind === "category" ? getRoleInsight(page.slug) : getRoleInsight("all", page.title.query)))
      .data;
  } catch (error) {
    if (error instanceof ApiUnavailable || error instanceof NotFound) return null;
    throw error;
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const page = resolvePath((await params).role);
  if (!page) return { title: "Role" };
  const insight = await load(page);
  return {
    title: `${page.label}: open roles, pay and hiring`,
    description: `Where ${page.label.toLowerCase()} roles are, who is hiring, what they advertise it pays and how fast hiring is moving, counted from open roles on employers' own job boards.`,
    alternates: { canonical: absoluteUrl(`/paths/${page.slug}`) },
    robots: insight ? robotsFor(insight.open_roles) : undefined,
  };
}

export default async function PathPageView({ params }: Props) {
  const page = resolvePath((await params).role);
  if (!page) notFound();
  const insight = await load(page);
  const countries = await getCountries()
    .then((c) => c.data)
    .catch(() => []);
  const slugs = countrySlugs(countries);
  const trail = [
    { name: "ERIO", path: "/" },
    { name: "Role explorer", path: "/paths" },
    { name: page.label, path: `/paths/${page.slug}` },
  ];
  const jobsLink = page.kind === "category" ? `/search?role=${page.slug}` : `/jobs/role/${page.slug}`;
  const related = relatedPaths(page);
  const countryRef = (code: string) => countries.find((c) => c.code === code);
  /** The landing page for this role in a country, when the country is known. */
  const placeHref = (code: string): string | null => {
    const country = countryRef(code);
    if (!country) return null;
    const ref = { code: country.code, name: country.name };
    return landingPath(
      page.kind === "category"
        ? { kind: "country-role", country: ref, role: page.slug }
        : { kind: "country-title", country: ref, title: page.title },
      slugs,
    );
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: scriptJson(breadcrumbJsonLd(trail)) }} />
      <div className="page-header">
        <div className="wrap">
          <nav className="jd-crumbs" aria-label="Breadcrumb">
            <Link href="/">Home</Link>
            {" / "}
            <Link href="/paths">Role explorer</Link>
          </nav>
          <div className="sect-eye">◉ {page.kind === "category" ? "Field" : "Job title"}</div>
          <h1 className="page-title">{page.label}</h1>
          {insight && (
            <div className={styles.stats}>
              <Stat value={formatCount(insight.open_roles)} label="Open roles" href={jobsLink} />
              <Stat value={percent(insight.remote_pct)} label="Remote" />
              <Stat
                value={`${insight.net_30d >= 0 ? "+" : "−"}${formatCount(Math.abs(insight.net_30d))}`}
                label="Net roles in 30 days"
              />
              <Stat value={percent(insight.pay_stated_pct)} label="State pay" />
            </div>
          )}
          <div className="hero-actions" style={{ marginTop: 22 }}>
            <Link className="btn-acc" href={jobsLink}>
              See the open roles
            </Link>
            <Link className="btn-ghost" href={`/salary?role=${page.category}`}>
              Pay in this field
            </Link>
          </div>
        </div>
      </div>
      <div className="wrap">
        {insight ? (
          <>
            <section className={styles.section}>
              <h2 className={styles.h2}>How fast it is hiring</h2>
              <p className={styles.note}>
                {formatCount(insight.added_30d)} roles added and {formatCount(insight.removed_30d)} closed in the
                last 30 days, so the net is {insight.net_30d >= 0 ? "+" : "−"}
                {formatCount(Math.abs(insight.net_30d))}.
                {page.kind === "title" && " For a title, these two counts use jobs whose title contains every word of it."}
              </p>
              <div className={styles.card}>
                <FlowChart flow={insight.flow} />
              </div>
            </section>

            <section className={styles.section}>
              <div className={styles.grid}>
                <div className={styles.card}>
                  <h2 className={styles.h2}>Top countries</h2>
                  <p className={styles.note}>Where the roles are based.</p>
                  <BarList
                    rows={insight.countries.map((c) => ({ key: c.code, label: c.name, count: c.roles }))}
                    href={(r) => placeHref(r.key)}
                  />
                </div>
                <div className={styles.card}>
                  <h2 className={styles.h2}>Top cities</h2>
                  <p className={styles.note}>Cities with the most open roles.</p>
                  <BarList
                    rows={insight.cities.map((c) => ({
                      key: `${c.city}-${c.country_code}`,
                      label: c.country ? `${c.city}, ${c.country}` : c.city,
                      count: c.roles,
                    }))}
                  />
                </div>
              </div>
            </section>

            <section className={styles.section}>
              <div className={styles.grid}>
                <div className={styles.card}>
                  <h2 className={styles.h2}>Who is hiring</h2>
                  <p className={styles.note}>Employers with the most open roles here.</p>
                  <BarList
                    rows={insight.employers.map((e) => ({ key: e.name, label: e.name, count: e.roles }))}
                    href={(r) => {
                      const employer = insight.employers.find((e) => e.name === r.key);
                      return companyHref(r.key, employer?.slug);
                    }}
                  />
                </div>
                <div className={styles.card}>
                  <h2 className={styles.h2}>What employers advertise they pay</h2>
                  <p className={styles.note}>
                    Yearly pay, per currency, never converted. Shown only where at least 10 roles state it;{" "}
                    {formatCount(insight.pay_stated_roles)} of {formatCount(insight.open_roles)} open roles state
                    pay in some form.
                  </p>
                  {insight.pay.length ? (
                    <PayRanges rows={insight.pay} />
                  ) : (
                    <p className={styles.empty}>Too few roles state a yearly range to show a figure.</p>
                  )}
                  {insight.pay_sampled && (
                    <p className={styles.small}>Figures use the most recent 10,000 roles that state yearly pay.</p>
                  )}
                </div>
              </div>
            </section>
          </>
        ) : (
          <section className={styles.section}>
            <div className="empty" role="alert">
              <h3>This page is unavailable right now</h3>
              <p>The job index could not be reached. Please try again in a minute.</p>
            </div>
          </section>
        )}

        <section className={styles.section}>
          <h2 className={styles.h2}>How to get started</h2>
          <p className={styles.note}>{STARTER_NOTES[page.category] ?? ""}</p>
        </section>

        <section className={styles.section} style={{ paddingBottom: 64 }}>
          <h2 className={styles.h2}>Related roles</h2>
          <div className={styles.list}>
            {related.map((r) => (
              <Link className={styles.co} key={r.slug} href={`/paths/${r.slug}`}>
                <span className={styles.coName}>{r.label}</span>
              </Link>
            ))}
          </div>
          <p className={styles.small}>
            <Link href="/paths">See every role</Link>
          </p>
        </section>
      </div>
    </>
  );
}
