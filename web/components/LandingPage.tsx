import Link from "next/link";

import { JobCard } from "@/components/JobCard";
import { formatCount, ROLE_LABELS } from "@/lib/format";
import {
  breadcrumbJsonLd,
  type Crumb,
  companyHref,
  headline,
  isThin,
  JOB_TITLES,
  landingPath,
  roleLabel,
  scriptJson,
  THIN_PAGE_MIN,
} from "@/lib/seo";
import { landingJobs, parentLanding, type ResolvedLanding } from "@/lib/seo-data";

import styles from "./LandingPage.module.css";

/** Query for the filtered search page that matches this landing page (that page is kept out of search engines). */
function searchHref(resolved: ResolvedLanding): string {
  const { landing } = resolved;
  const params = new URLSearchParams();
  if (landing.kind !== "role-title") {
    params.set("country", landing.country.code);
    params.set("ww", "0");
  }
  if (landing.kind === "country-role") params.set("role", landing.role);
  if (landing.kind === "country-title" || landing.kind === "role-title") params.set("q", landing.title.query);
  if (landing.kind === "country-city") params.set("q", landing.city);
  return `/search?${params.toString()}`;
}

function crumbs(resolved: ResolvedLanding): Crumb[] {
  const { landing, slugs } = resolved;
  const trail: Crumb[] = [{ name: "ERIO", path: "/" }];
  const parent = parentLanding(landing);
  if (parent) trail.push({ name: headline(parent), path: landingPath(parent, slugs) });
  trail.push({ name: headline(landing), path: landingPath(landing, slugs) });
  return trail;
}

export async function LandingPage({ resolved }: { resolved: ResolvedLanding }) {
  const { landing, slugs, countries, country } = resolved;
  const parent = parentLanding(landing);
  const [page, parentPage] = await Promise.all([landingJobs(landing), parent ? landingJobs(parent, 1) : null]);
  const total = page.meta.total;
  const trail = crumbs(resolved);
  const countryNames = Object.fromEntries(countries.map((c) => [c.code, c.name]));
  const here = landingPath(landing, slugs);

  // Role links inside the country: a country page's own facets, or the parent's for a sub-page.
  const roleFacets = (parentPage ?? page).meta.facets.role;
  const roleLinks =
    landing.kind === "role-title"
      ? []
      : Object.keys(ROLE_LABELS)
          .filter((role) => (roleFacets[role] ?? 0) >= THIN_PAGE_MIN)
          .map((role) => ({
            label: roleLabel(role),
            count: roleFacets[role] ?? 0,
            href: landingPath({ kind: "country-role", country: landing.country, role }, slugs),
          }));
  const cityLinks =
    landing.kind === "country" && country
      ? country.cities
          .filter((c) => c.job_count >= THIN_PAGE_MIN)
          .slice(0, 12)
          .map((c) => ({
            label: c.name,
            count: c.job_count,
            href: landingPath({ kind: "country-city", country: landing.country, city: c.name }, slugs),
          }))
      : [];
  const countryLinks =
    landing.kind === "role-title"
      ? [...countries]
          .sort((a, b) => b.local_job_count - a.local_job_count)
          .slice(0, 12)
          .map((c) => ({
            label: c.name,
            count: c.local_job_count,
            href: landingPath(
              { kind: "country-title", country: { code: c.code, name: c.name }, title: landing.title },
              slugs,
            ),
          }))
      : [];
  const titleLinks =
    landing.kind === "country"
      ? JOB_TITLES.slice(0, 12).map((title) => ({
          label: title.label,
          href: landingPath({ kind: "country-title", country: landing.country, title }, slugs),
        }))
      : [];
  const employers = [...new Map(page.data.map((j) => [j.company.name, j.company.name])).values()].slice(0, 12);

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: scriptJson(breadcrumbJsonLd(trail)) }} />
      <div className="page-header">
        <div className="wrap">
          <nav className="jd-crumbs" aria-label="Breadcrumb">
            <Link href="/">Home</Link>
            {parent && (
              <>
                {" / "}
                <Link href={landingPath(parent, slugs)}>{headline(parent)}</Link>
              </>
            )}
          </nav>
          <div className="sect-eye">◉ Job index</div>
          <h1 className="page-title">{headline(landing)}</h1>
          <p className={styles.lead}>
            {total === 0
              ? "No open roles match right now. New ones are indexed every hour."
              : `${formatCount(total)} open ${total === 1 ? "role" : "roles"} from company career pages and job boards, updated every hour. Each listing links to the employer's own page to apply.`}
          </p>
          <div className="hero-actions">
            <Link className="btn-acc" href={searchHref(resolved)}>
              Filter these jobs
            </Link>
            {parent && (
              <Link className="btn-ghost" href={landingPath(parent, slugs)}>
                All {headline(parent).toLowerCase()}
              </Link>
            )}
          </div>
        </div>
      </div>
      <section>
        <div className="wrap">
          {isThin(total) && total > 0 && (
            <p className={styles.note}>
              Only a few roles match so far. The wider{" "}
              <Link href={parent ? landingPath(parent, slugs) : searchHref(resolved)}>
                {parent ? headline(parent) : "job search"}
              </Link>{" "}
              has more.
            </p>
          )}
          {page.data.length > 0 && (
            <>
              <h2 className={styles.h2}>Latest openings</h2>
              <div className="jg" role="list" aria-label="Latest openings">
                {page.data.map((job) => (
                  <JobCard key={job.canonical_id} job={job} countryNames={countryNames} />
                ))}
              </div>
              {page.meta.next_cursor && (
                <p className={styles.more}>
                  Showing the latest {page.data.length} of {formatCount(total)}.{" "}
                  <Link href={searchHref(resolved)}>See them all in search</Link>
                </p>
              )}
            </>
          )}
          <LinkGroup title="Employers hiring" links={employers.map((name) => ({ label: name, href: companyHref(name) }))} />
          {landing.kind !== "role-title" && (
            <LinkGroup title={`By role in ${landing.country.name}`} links={roleLinks} hide={here} />
          )}
          <LinkGroup title="Top cities" links={cityLinks} />
          <LinkGroup title="Popular job titles" links={titleLinks} />
          {landing.kind === "role-title" && (
            <LinkGroup title={`${landing.title.label} jobs by country`} links={countryLinks} />
          )}
        </div>
      </section>
    </>
  );
}

function LinkGroup({
  title,
  links,
  hide,
}: {
  title: string;
  links: { label: string; href: string; count?: number }[];
  hide?: string;
}) {
  const shown = links.filter((l) => l.href !== hide);
  if (!shown.length) return null;
  return (
    <>
      <h2 className={styles.h2}>{title}</h2>
      <div className="qf-row">
        {shown.map((l) => (
          <Link key={l.href + l.label} className="qf" href={l.href}>
            {l.label}
            {l.count !== undefined && <span className="qf-n"> {formatCount(l.count)}</span>}
          </Link>
        ))}
      </div>
    </>
  );
}
