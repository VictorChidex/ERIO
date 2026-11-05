import type { Metadata } from "next";
import Link from "next/link";

import { ApiUnavailable, getPlatforms, getStats, type Platform, type Stats } from "@/lib/api";
import { ageLabel, formatCount } from "@/lib/format";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Coverage",
  description: "Live status of every job source ERIO reads, with board counts and fetch success.",
};

const STATUS: Record<Platform["status"], { cls: string; label: string }> = {
  live: { cls: "live", label: "Live" },
  indexing: { cls: "idx", label: "Indexing" },
  scheduled: { cls: "sched", label: "Scheduled" },
  paused: { cls: "sched", label: "Paused" },
};

async function load(): Promise<{ platforms: Platform[]; stats: Stats } | null> {
  try {
    const [platforms, stats] = await Promise.all([getPlatforms(), getStats()]);
    return { platforms: platforms.data, stats };
  } catch (error) {
    if (error instanceof ApiUnavailable) return null;
    throw error;
  }
}

export default async function CoveragePage() {
  const data = await load();
  const live = data?.platforms.filter((p) => p.status === "live").length ?? 0;

  return (
    <>
      <div className="page-header">
        <div className="wrap">
          <div className="sect-eye">◉ Platform Coverage</div>
          <h1 className="page-title">Straight from the source.</h1>
          <p className="page-sub">
            Each source is crawled on its own schedule with rate limiting, failure tracking and
            automatic retries — and never mistakes a failed fetch for a closed job.
          </p>
          <div className="cov-stats-row">
            <div className="cov-stat">
              <div className="cov-stat-num">{data ? `${live}/${data.platforms.length}` : "—"}</div>
              <div className="cov-stat-lbl">Sources live</div>
            </div>
            <div className="cov-stat">
              <div className="cov-stat-num">{data ? formatCount(data.stats.boards_tracked) : "—"}</div>
              <div className="cov-stat-lbl">Company boards</div>
            </div>
            <div className="cov-stat">
              <div className="cov-stat-num">{data ? formatCount(data.stats.total_jobs) : "—"}</div>
              <div className="cov-stat-lbl">Jobs indexed</div>
            </div>
            <div className="cov-stat">
              <div className="cov-stat-num">
                {data?.stats.refresh_lag_minutes != null ? `${Math.max(1, Math.round(data.stats.refresh_lag_minutes))}m` : "—"}
              </div>
              <div className="cov-stat-lbl">Refresh lag</div>
            </div>
          </div>
        </div>
      </div>
      <section>
        <div className="wrap">
          <div className="cov-legend">
            <span className="cl">
              <span className="cldot cl-live" />
              Live — fetched successfully in the last hour
            </span>
            <span className="cl">
              <span className="cldot cl-idx" />
              Indexing — connector built, first runs under way
            </span>
            <span className="cl">
              <span className="cldot cl-sched" />
              Scheduled — connector coming next
            </span>
          </div>
          {data ? (
            <div className="pg" role="list" aria-label="Sources">
              {data.platforms.map((p) => (
                <div className="pc" role="listitem" key={p.slug}>
                  <div className="pc-top">
                    <span className="pc-name">{p.name}</span>
                    <span className={`pc-dot ${STATUS[p.status].cls}`} aria-hidden="true" />
                  </div>
                  <div className="pc-jobs">
                    {formatCount(p.job_count)} jobs · {formatCount(p.boards)} boards
                  </div>
                  <div className={`pc-status ${STATUS[p.status].cls}`}>{STATUS[p.status].label}</div>
                  <div className="pc-meta">
                    {p.last_success_at ? `Last success ${ageLabel(p.last_success_at)}` : "No fetch yet"}
                    {p.fetch_success_rate_24h != null && ` · ${Math.round(p.fetch_success_rate_24h * 100)}% ok (24h)`}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty" role="alert">
              <h3>Coverage is unavailable right now</h3>
              <p>The job index could not be reached. Please try again in a minute.</p>
            </div>
          )}
          <p className="cov-note">
            Job boards whose terms forbid automated collection (LinkedIn, Indeed, Glassdoor and
            similar) are never crawled. They can join later only through licensed feeds.{" "}
            <Link href="https://github.com/VictorChidex/ERIO/blob/main/docs/sources.md">How sources are reviewed</Link>
          </p>
        </div>
      </section>
    </>
  );
}
