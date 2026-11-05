import Link from "next/link";

import { CountryPicker } from "@/components/CountryPicker";
import { FilterForm } from "@/components/FilterForm";
import { SearchGlobe } from "@/components/GlobeLazy";
import { HeaderCountrySelect } from "@/components/HeaderCountrySelect";
import { JobCard } from "@/components/JobCard";
import { LoadMore } from "@/components/LoadMore";
import { ApiUnavailable, type Countries, getCountries, type JobsPage, searchJobs } from "@/lib/api";
import { type Filters, toApiParams, toQuery } from "@/lib/filters";
import { formatCount, ROLE_LABELS, TYPE_LABELS } from "@/lib/format";
import { globeData } from "@/lib/globe";

const SALARY_OPTIONS = [0, 40_000, 80_000, 150_000];
const POPULAR = 8;

async function load(filters: Filters): Promise<{ page: JobsPage; countries: Countries } | null> {
  try {
    const [page, countries] = await Promise.all([searchJobs(toApiParams(filters)), getCountries()]);
    return { page, countries };
  } catch (error) {
    if (error instanceof ApiUnavailable) return null;
    throw error;
  }
}

export async function SearchView({
  filters,
  eyebrow = "⌕ Job Search",
  title = "Find your next role, anywhere.",
  intro = "Filter by any of the world's countries. Worldwide-remote roles are open to you wherever you live.",
}: {
  filters: Filters;
  eyebrow?: string;
  title?: string;
  intro?: string;
}) {
  const data = await load(filters);
  if (!data) {
    return (
      <div className="page-header">
        <div className="wrap">
          <div className="sect-eye">{eyebrow}</div>
          <h1 className="page-title">{title}</h1>
          <div className="empty" role="alert">
            <div className="empty-ico">◌</div>
            <h3>Search is unavailable right now</h3>
            <p>The job index could not be reached. Please try again in a minute.</p>
          </div>
        </div>
      </div>
    );
  }

  const { page, countries } = data;
  const facets = page.meta.facets;
  const countryNames = Object.fromEntries(countries.data.map((c) => [c.code, c.name]));
  const countryFiltered = filters.countries.length > 0;
  const allTypesShown = filters.types.length === 0;
  const one = filters.countries.length === 1 ? filters.countries[0] : null;
  const where = one ? `in ${countryNames[one] ?? one}` : countryFiltered ? `in ${filters.countries.length} countries` : "worldwide";
  const local = one ? (facets.country[one] ?? 0) : 0;
  const worldwideHits = one && filters.ww ? Math.max(0, page.meta.total - local) : 0;
  const popular = [...countries.data]
    .filter((c) => c.job_count > 0)
    .sort((a, b) => b.job_count - a.job_count)
    .slice(0, POPULAR);

  return (
    <FilterForm>
      <div className="page-header">
        <div className="wrap">
          <div className="ph-row">
            <div className="ph-text">
              <div className="sect-eye">{eyebrow}</div>
              <h1 className="page-title">{title}</h1>
              <p className="page-sub">{intro}</p>
              <div className="search-wrap search-wrap-inline">
                <div className="search-box">
                  <span className="si" aria-hidden="true">
                    ⌕
                  </span>
                  <input
                    type="text"
                    id="si2"
                    name="q"
                    defaultValue={filters.q}
                    placeholder="Title, company or city…"
                    autoComplete="off"
                    aria-label="Search jobs"
                  />
                  <HeaderCountrySelect countries={countries.data} filters={filters} />
                  <button className="search-btn" type="submit">
                    Search
                  </button>
                </div>
              </div>
            </div>
            <div className="ph-globe">
              <SearchGlobe data={globeData(countries)} filters={filters} />
            </div>
          </div>
        </div>
      </div>

      <section>
        <div className="wrap">
          <div className="r-layout">
            <aside className="sidebar" aria-label="Search filters">
              <div className="sb-head">
                <p className="sb-title">Filters</p>
                <Link className="sb-reset" href="/search">
                  Reset all
                </Link>
              </div>
              <div className="fg">
                <div className="fg-label">Country</div>
                <CountryPicker countries={countries.data} selected={filters.countries} counts={facets.country} />
                <label className="ww-toggle">
                  <input type="checkbox" name="ww" value="1" defaultChecked={filters.ww} />{" "}
                  <span>Include worldwide-remote roles</span>{" "}
                  <span className="fc">{countries.meta.worldwide_remote_jobs}</span>
                </label>
              </div>
              <fieldset className="fg">
                <legend className="fg-label">Work type</legend>
                <div className="fo">
                  {Object.entries(TYPE_LABELS).map(([value, label]) => (
                    <label key={value}>
                      <input
                        type="checkbox"
                        name="type"
                        value={value}
                        defaultChecked={allTypesShown || filters.types.includes(value)}
                      />{" "}
                      {label} <span className="fc">{facets.remote_status[value] ?? 0}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset className="fg">
                <legend className="fg-label">Role</legend>
                <div className="fo">
                  {Object.entries(ROLE_LABELS).map(([value, label]) => (
                    <label key={value}>
                      <input type="checkbox" name="role" value={value} defaultChecked={filters.roles.includes(value)} />{" "}
                      {label} <span className="fc">{facets.role[value] ?? 0}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset className="fg">
                <legend className="fg-label">
                  Salary <span className="fg-note">USD equivalent</span>
                </legend>
                <div className="fo">
                  {SALARY_OPTIONS.map((value) => (
                    <label key={value}>
                      <input
                        type="radio"
                        name="salary"
                        value={value}
                        defaultChecked={(filters.salary ?? 0) === value}
                      />{" "}
                      {value ? `$${value / 1000}k+` : "Any"}
                    </label>
                  ))}
                </div>
              </fieldset>
              <noscript>
                <button className="btn-acc" type="submit">
                  Apply filters
                </button>
              </noscript>
            </aside>

            <div className="results-main">
              <div className="rh">
                <span className="rc" role="status">
                  <strong>{formatCount(page.meta.total)}</strong> job{page.meta.total === 1 ? "" : "s"} {where}
                  {one && filters.ww && worldwideHits > 0 && (
                    <span className="rc-sub">
                      {" "}
                      ({formatCount(local)} local · {formatCount(worldwideHits)} worldwide-remote)
                    </span>
                  )}
                </span>
                <select className="rsort" name="sort" defaultValue={filters.sort} aria-label="Sort results">
                  <option value="recent">Most recent</option>
                  <option value="salary">Salary: high to low</option>
                  {filters.q && <option value="relevance">Best match</option>}
                </select>
              </div>

              <div className="af-row" aria-label={countryFiltered ? "Selected countries" : "Popular countries"}>
                {countryFiltered ? (
                  <>
                    {filters.countries.map((code) => (
                      <span className="af" key={code}>
                        {countryNames[code] ?? code}
                        <Link
                          href={`/search${toQuery(filters, { countries: filters.countries.filter((c) => c !== code) })}`}
                          aria-label={`Remove ${countryNames[code] ?? code}`}
                          scroll={false}
                        >
                          ×
                        </Link>
                      </span>
                    ))}
                    <Link className="af-clear" href={`/search${toQuery(filters, { countries: [] })}`} scroll={false}>
                      Clear countries
                    </Link>
                  </>
                ) : (
                  <>
                    <span className="af-lbl">Popular:</span>
                    {popular.map((c) => (
                      <Link
                        key={c.code}
                        className="qf"
                        href={`/search${toQuery(filters, { countries: [c.code] })}`}
                        scroll={false}
                      >
                        {c.name} <span className="qf-n">{formatCount(c.job_count)}</span>
                      </Link>
                    ))}
                  </>
                )}
              </div>

              {page.data.length ? (
                <div className="jg" role="list" aria-label="Jobs">
                  {page.data.map((job) => (
                    <JobCard
                      key={job.canonical_id}
                      job={job}
                      countryNames={countryNames}
                      openToYou={countryFiltered && job.remote_scope === "worldwide"}
                    />
                  ))}
                </div>
              ) : (
                <div className="empty">
                  <div className="empty-ico">◌</div>
                  <h3>No matching listings{one ? ` in ${countryNames[one] ?? one}` : ""} yet</h3>
                  {one && !filters.ww ? (
                    <>
                      <p>
                        Turn on <b>worldwide-remote roles</b> to see {countries.meta.worldwide_remote_jobs} jobs open
                        to applicants in {countryNames[one] ?? one}, or loosen the other filters.
                      </p>
                      <Link className="btn-acc" href={`/search${toQuery(filters, { ww: true })}`}>
                        Show worldwide-remote roles
                      </Link>
                    </>
                  ) : (
                    <>
                      <p>Try removing a filter or searching a nearby country.</p>
                      <Link className="btn-ghost" href="/search">
                        Reset filters
                      </Link>
                    </>
                  )}
                </div>
              )}

              {page.meta.next_cursor ? (
                <LoadMore
                  query={toQuery(filters)}
                  cursor={page.meta.next_cursor}
                  countryNames={countryNames}
                  countryFiltered={countryFiltered}
                  shown={page.data.length}
                  total={page.meta.total}
                />
              ) : (
                page.data.length > 0 && (
                  <div className="load-more-wrap">
                    <p className="load-hint">
                      Showing all {formatCount(page.meta.total)} job{page.meta.total === 1 ? "" : "s"}
                    </p>
                  </div>
                )
              )}
            </div>
          </div>
        </div>
      </section>
    </FilterForm>
  );
}
