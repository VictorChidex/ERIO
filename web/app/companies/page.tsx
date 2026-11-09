import type { Metadata } from "next";
import Link from "next/link";

import styles from "@/app/pulse/insights.module.css";
import { ApiUnavailable, getCompanies, type Companies } from "@/lib/api";
import { formatCount } from "@/lib/format";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Companies",
  description: "Employers with open roles in the ERIO index, with what each one is hiring for.",
};

type Search = { q?: string; country?: string; sort?: string; page?: string };

async function load(search: Search): Promise<Companies | null> {
  const page = Math.max(1, Math.min(10_000, Number(search.page) || 1));
  try {
    return await getCompanies({
      q: search.q?.slice(0, 100),
      country: /^[A-Za-z]{2}$/.test(search.country ?? "") ? search.country : undefined,
      sort: search.sort === "name" ? "name" : "roles",
      page,
      per_page: 24,
    });
  } catch (error) {
    if (error instanceof ApiUnavailable) return null;
    throw error;
  }
}

function link(search: Search, page: number): string {
  const params = new URLSearchParams();
  if (search.q) params.set("q", search.q);
  if (search.country) params.set("country", search.country);
  if (search.sort === "name") params.set("sort", "name");
  if (page > 1) params.set("page", String(page));
  const query = params.toString();
  return query ? `/companies?${query}` : "/companies";
}

export default async function CompaniesPage({ searchParams }: { searchParams: Promise<Search> }) {
  const search = await searchParams;
  const data = await load(search);
  const page = data?.meta.page ?? 1;
  const last = data ? Math.max(1, Math.ceil(data.meta.total / data.meta.per_page)) : 1;

  return (
    <>
      <div className="page-header">
        <div className="wrap">
          <div className="sect-eye">◉ Companies</div>
          <h1 className="page-title">Who is hiring.</h1>
          <p className="page-sub">
            Every employer ERIO follows that has open roles right now. Open one to see what it
            hires for, where, and how its openings change over time.
          </p>
          <form className={styles.search} action="/companies" role="search">
            <input className={styles.input} type="search" name="q" defaultValue={search.q ?? ""} placeholder="Company name" aria-label="Company name" maxLength={100} />
            <input className={styles.input} type="text" name="country" defaultValue={search.country ?? ""} placeholder="Country code, e.g. NG" aria-label="Country code" maxLength={2} pattern="[A-Za-z]{2}" style={{ minWidth: 0, width: 190 }} />
            <select className={styles.input} name="sort" defaultValue={search.sort === "name" ? "name" : "roles"} aria-label="Sort">
              <option value="roles">Most open roles</option>
              <option value="name">Name</option>
            </select>
            <button className={styles.button} type="submit">
              Search
            </button>
          </form>
        </div>
      </div>
      <div className="wrap">
        <section className={styles.section}>
          {data ? (
            data.data.length ? (
              <>
                <p className={styles.note}>
                  {formatCount(data.meta.total)} {data.meta.total === 1 ? "company" : "companies"}
                  {search.q ? ` matching “${search.q}”` : ""}
                  {search.country ? ` hiring in ${search.country.toUpperCase()}` : ""}
                </p>
                <div className={styles.list}>
                  {data.data.map((c) => (
                    <Link className={styles.co} href={`/company/${c.slug}`} key={c.slug}>
                      <span>
                        <span className={styles.coName}>{c.name}</span>
                        <span className={styles.coSub} style={{ display: "block" }}>
                          {c.domain ?? "No website listed"}
                        </span>
                      </span>
                      <span className={styles.coNum}>{formatCount(c.open_roles)} open</span>
                    </Link>
                  ))}
                </div>
                <div className={styles.pager}>
                  {page > 1 ? <Link href={link(search, page - 1)}>← Previous</Link> : <span />}
                  <span>
                    Page {page} of {last}
                  </span>
                  {page < last ? <Link href={link(search, page + 1)}>Next →</Link> : <span />}
                </div>
              </>
            ) : (
              <div className="empty">
                <h3>No companies match</h3>
                <p>Try a different name or country, or clear the search.</p>
                <Link className="btn-ghost" href="/companies">
                  Clear search
                </Link>
              </div>
            )
          ) : (
            <div className="empty" role="alert">
              <h3>Companies are unavailable right now</h3>
              <p>The job index could not be reached. Please try again in a minute.</p>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
