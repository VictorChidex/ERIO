import Link from "next/link";

import { CountrySelect } from "@/components/CountrySelect";
import {
  ApiUnavailable,
  type Countries,
  getCountries,
  getPlatforms,
  getStats,
  type JobsPage,
  type Platform,
  searchJobs,
  type Stats,
} from "@/lib/api";
import { formatCount, salaryLabel } from "@/lib/format";

// Rendered per request so every number is live.
export const dynamic = "force-dynamic";

const QUICK_FILTERS: { label: string; query: string }[] = [
  { label: "Engineering", query: "role=engineering" },
  { label: "Product", query: "role=product" },
  { label: "Design", query: "role=design" },
  { label: "Data & ML", query: "role=data" },
  { label: "Remote", query: "type=remote" },
  { label: "$150k+", query: "salary=150000" },
];

const STATUS_CLASS: Record<Platform["status"], string> = {
  live: "live",
  indexing: "idx",
  scheduled: "sched",
  paused: "sched",
};

type HomeData = { stats: Stats; platforms: Platform[]; recent: JobsPage; countries: Countries };

async function load(): Promise<HomeData | null> {
  try {
    const [stats, platforms, recent, countries] = await Promise.all([
      getStats(),
      getPlatforms(),
      searchJobs({ per_page: 12, sort: "recent" }),
      getCountries(),
    ]);
    return { stats, platforms: platforms.data, recent, countries };
  } catch (error) {
    if (error instanceof ApiUnavailable) return null;
    throw error;
  }
}

function lag(minutes: number | null): { value: string; unit: string } {
  if (minutes === null) return { value: "—", unit: "" };
  if (minutes < 60) return { value: String(Math.max(1, Math.round(minutes))), unit: "m" };
  return { value: String(Math.round(minutes / 60)), unit: "h" };
}

export default async function HomePage() {
  const data = await load();
  const stats = data?.stats;
  const topCountries = (data?.countries.data ?? [])
    .filter((c) => c.local_job_count > 0)
    .sort((a, b) => b.local_job_count - a.local_job_count)
    .slice(0, 8);
  const sample = data?.recent.data[0];
  const refresh = lag(stats?.refresh_lag_minutes ?? null);

  return (
    <>
      <section id="hero">
        <div className="hero-glow" aria-hidden="true" />
        <div className="hero-in">
          <div className="hero-row">
            <div className="hero-text">
              <div className="eyebrow" role="status">
                <span className={stats ? "live-dot" : "live-dot down"} />
                {stats ? (
                  <>
                    Live — <span id="live-count">{formatCount(stats.total_jobs)}</span> jobs indexed
                  </>
                ) : (
                  "Index offline — try again shortly"
                )}
              </div>
              <h1 className="hero-h1">
                <span className="h1-gr">Every open job.</span>
                <br />
                One search.
              </h1>
              <p className="hero-sub">
                Jobs straight from employers&apos; applicant tracking systems — crawled every 15
                minutes, normalized into one record, and filterable by any country in the world.
              </p>
              <div className="hero-actions">
                <Link href="/search" className="btn-acc">
                  Search Jobs
                </Link>
                <Link href="/api" className="btn-ghost">
                  View API Docs
                </Link>
              </div>
            </div>
            <div className="globe-wrap globe-fallback">
              <div className="gf-card">
                <div className="gf-title">Jobs by country</div>
                {topCountries.length ? (
                  <ul className="gf-list">
                    {topCountries.map((c) => (
                      <li key={c.code}>
                        <Link href={`/search?country=${c.code}`}>
                          <span>{c.name}</span>
                          <span className="qf-n">{formatCount(c.local_job_count)}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="gf-empty">Countries appear here as jobs are indexed.</p>
                )}
                <Link href="/search" className="gf-all">
                  All 233 countries →
                </Link>
              </div>
            </div>
          </div>

          <form className="search-wrap" action="/search" method="get" role="search">
            <div className="search-box">
              <span className="si" aria-hidden="true">
                ⌕
              </span>
              <input
                type="text"
                id="si"
                name="q"
                placeholder={stats ? `Search ${formatCount(stats.total_jobs)} jobs...` : "Search jobs..."}
                autoComplete="off"
                aria-label="Search jobs"
              />
              <CountrySelect name="country" countries={data?.countries.data ?? []} />
              <button className="search-btn" type="submit">
                Search
              </button>
            </div>
            <div className="scan" aria-hidden="true" />
          </form>

          <nav className="qf-row" aria-label="Quick filters">
            <Link href="/search" className="qf on">
              All Roles
            </Link>
            {QUICK_FILTERS.map((f) => (
              <Link key={f.label} href={`/search?${f.query}`} className="qf">
                {f.label}
              </Link>
            ))}
          </nav>

          <div className="stats-grid">
            <div className="stat">
              <div className="snum">{stats ? formatCount(stats.total_jobs) : "—"}</div>
              <div className="slbl">Jobs Indexed</div>
            </div>
            <div className="stat">
              <div className="snum">{stats ? formatCount(stats.countries_with_jobs) : "—"}</div>
              <div className="slbl">Countries With Jobs</div>
            </div>
            <div className="stat">
              <div className="snum">{stats ? formatCount(stats.sources_live) : "—"}</div>
              <div className="slbl">Sources Live</div>
            </div>
            <div className="stat">
              <div className="snum">
                {refresh.value}
                <span className="u">{refresh.unit}</span>
              </div>
              <div className="slbl">Refresh Lag</div>
            </div>
          </div>
        </div>
      </section>

      {data && data.recent.data.length > 0 && (
        <div id="ticker" aria-label="Recently indexed jobs">
          <div className="tick-track">
            {[...data.recent.data, ...data.recent.data].map((job, i) => (
              <Link
                key={`${job.canonical_id}-${i}`}
                href={`/jobs/${job.canonical_id}`}
                className="ti"
                aria-hidden={i >= data.recent.data.length}
                tabIndex={i >= data.recent.data.length ? -1 : undefined}
              >
                <b>{job.company.name}</b> {job.title}
                <span className="tl">· {job.location_text ?? job.country_code ?? "Remote"}</span>
              </Link>
            ))}
          </div>
        </div>
      )}

      <section id="features">
        <div className="wrap">
          <div className="sect-eye">◉ Why ERIO</div>
          <h2 className="sect-h">The index built for builders.</h2>
          <p className="sect-p">
            Most job APIs are glorified job boards. ERIO is a true index — structured, normalized,
            and built from primary sources.
          </p>
          <div className="feat-grid">
            <div className="feat-card">
              <div className="feat-icon">⟳</div>
              <h3>Real-time crawling</h3>
              <p>Every company board is crawled every 15 minutes, politely and within each host&apos;s rate limits.</p>
            </div>
            <div className="feat-card">
              <div className="feat-icon">◉</div>
              <h3>Failure-aware indexing</h3>
              <p>A failed fetch never closes a job. A job closes only when its source stops listing it, twice.</p>
            </div>
            <div className="feat-card">
              <div className="feat-icon">⌥</div>
              <h3>Normalized schema</h3>
              <p>
                Every job resolves to one <code>JobRecord</code> — country, remote scope, salary in
                the posted currency, and its source.
              </p>
            </div>
            <div className="feat-card">
              <div className="feat-icon">⊕</div>
              <h3>Every country</h3>
              <p>Filter by any of 233 countries. Remote roles show wherever they accept applicants.</p>
            </div>
            <div className="feat-card">
              <div className="feat-icon">⚡</div>
              <h3>One API</h3>
              <p>
                Search, filter and paginate through a single <code>GET /v1/jobs</code> call, with
                facet counts and cursor pagination.
              </p>
            </div>
            <div className="feat-card">
              <div className="feat-icon">⊞</div>
              <h3>Primary sources only</h3>
              <p>Employer-published ATS feeds — never scraped from job boards whose terms forbid it.</p>
            </div>
          </div>
        </div>
      </section>

      <section id="cov-teaser">
        <div className="wrap">
          <div className="cov-tease-inner">
            <div>
              <div className="sect-eye">◉ Coverage</div>
              <h2 className="sect-h cov-h">
                Straight from
                <br />
                the source.
              </h2>
              <p className="cov-p">
                {data
                  ? `${data.platforms.filter((p) => p.status === "live").length} of ${data.platforms.length} first-release sources live, tracking ${formatCount(stats?.boards_tracked ?? 0)} company boards. More connect every week.`
                  : "Source status is unavailable right now."}
              </p>
              <Link href="/coverage" className="btn-acc">
                View coverage →
              </Link>
            </div>
            <div className="cov-badges" aria-label="Source status">
              <div className="cb-row">
                {(data?.platforms ?? []).map((p) => (
                  <span key={p.slug} className={`cb ${STATUS_CLASS[p.status]}`} title={p.status}>
                    {p.name}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="dev-cta">
        <div className="wrap">
          <div className="cta-inner">
            <div>
              <h2 className="sect-h cov-h">Built for developers.</h2>
              <p className="cov-p">
                Bearer-token auth. OpenAPI 3.1 spec. Cursor pagination. Rate-limit headers. Facet
                counts for every filter. The same API this website runs on.
              </p>
              <div className="cta-actions">
                <Link href="/api" className="btn-acc">
                  Explore the API
                </Link>
                <a href="/openapi.json" className="btn-ghost">
                  OpenAPI spec
                </a>
              </div>
            </div>
            <div className="code-wrap">
              <div className="ctop">
                <div className="dots">
                  <span className="dot-r" />
                  <span className="dot-y" />
                  <span className="dot-g" />
                </div>
                <span className="ctitle">GET /v1/jobs?per_page=1</span>
              </div>
              <pre className="code">
                {sample ? (
                  <>
                    <span className="cm">{"{"}</span>
                    {"\n  "}
                    <span className="ck">&quot;data&quot;</span>
                    <span className="cm">{": [{"}</span>
                    {"\n    "}
                    <span className="ck">&quot;title&quot;</span>
                    <span className="cm">: </span>
                    <span className="cv">{JSON.stringify(sample.title)}</span>
                    <span className="cm">,</span>
                    {"\n    "}
                    <span className="ck">&quot;company&quot;</span>
                    <span className="cm">: </span>
                    <span className="cv">{JSON.stringify(sample.company.name)}</span>
                    <span className="cm">,</span>
                    {"\n    "}
                    <span className="ck">&quot;country_code&quot;</span>
                    <span className="cm">: </span>
                    <span className="cv">{JSON.stringify(sample.country_code)}</span>
                    <span className="cm">,</span>
                    {"\n    "}
                    <span className="ck">&quot;role_category&quot;</span>
                    <span className="cm">: </span>
                    <span className="cv">{JSON.stringify(sample.role_category)}</span>
                    <span className="cm">,</span>
                    {"\n    "}
                    <span className="ck">&quot;salary&quot;</span>
                    <span className="cm">: </span>
                    <span className="cv">{JSON.stringify(salaryLabel(sample))}</span>
                    <span className="cm">,</span>
                    {"\n    "}
                    <span className="ck">&quot;sources&quot;</span>
                    <span className="cm">: </span>
                    <span className="cv">{JSON.stringify(sample.sources)}</span>
                    {"\n  "}
                    <span className="cm">{"}],"}</span>
                    {"\n  "}
                    <span className="ck">&quot;meta&quot;</span>
                    <span className="cm">{": { "}</span>
                    <span className="ck">&quot;total&quot;</span>
                    <span className="cm">: </span>
                    <span className="cn">{data?.recent.meta.total}</span>
                    <span className="cm">{" }"}</span>
                    {"\n"}
                    <span className="cm">{"}"}</span>
                  </>
                ) : (
                  <span className="cm">{"{ \"data\": [], \"meta\": { \"total\": 0 } }"}</span>
                )}
              </pre>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
