import Link from "next/link";

import type { CoverageRow } from "@/lib/api";
import { ageLabel, formatCount } from "@/lib/format";

const KINDS = [
  { key: "ats", label: "Applicant tracking systems", short: "ATS" },
  { key: "board", label: "Job-board platforms", short: "Job boards" },
] as const;

const STATUS_CLASS: Record<string, string> = {
  Verified: "ok",
  Partial: "part",
  Blocked: "blk",
};

// A platform is live when this many of its boards were read successfully in the last two days.
const LIVE_BOARDS = 3;

function percent(share: number | null): string {
  return share === null ? "—" : `${Math.round(share * 100)}%`;
}

export type CoverageFilter = { kind?: string; status?: string };

function href(filter: CoverageFilter): string {
  const query = new URLSearchParams();
  if (filter.kind) query.set("kind", filter.kind);
  if (filter.status) query.set("status", filter.status);
  const text = query.toString();
  return text ? `/coverage?${text}#checklist` : "/coverage#checklist";
}

export function CoverageChecklist({ rows, filter }: { rows: CoverageRow[]; filter: CoverageFilter }) {
  const shown = rows.filter(
    (r) => (!filter.kind || r.kind === filter.kind) && (!filter.status || r.status === filter.status),
  );
  const statuses = ["Verified", "Partial", "Blocked"];

  return (
    <section id="checklist" aria-labelledby="checklist-title">
      <div className="wrap">
        <h2 className="cov-h" id="checklist-title">
          The 78-platform checklist
        </h2>
        <p className="cov-p">
          A platform counts as <strong>verified</strong> only when live runs on two or more of its real boards
          fetched, parsed and normalized every job, and as <strong>live</strong> while at least{" "}
          {LIVE_BOARDS} of its boards were read successfully in the last two days. Platforms that turn crawlers
          away are shown as blocked and are never worked around.
        </p>
        <div className="cov-stats-row">
          {KINDS.map((k) => {
            const group = rows.filter((r) => r.kind === k.key);
            const verified = group.filter((r) => r.status === "Verified").length;
            return (
              <div className="cov-stat" key={k.key}>
                <div className="cov-stat-num">
                  {verified}/{group.length}
                </div>
                <div className="cov-stat-lbl">{k.label} verified</div>
              </div>
            );
          })}
          <div className="cov-stat">
            <div className="cov-stat-num">{rows.filter((r) => r.status === "Verified").length}/{rows.length}</div>
            <div className="cov-stat-lbl">Platforms verified</div>
          </div>
          <div className="cov-stat">
            <div className="cov-stat-num">
              {rows.filter((r) => r.live).length}/{rows.length}
            </div>
            <div className="cov-stat-lbl">Platforms live now</div>
          </div>
        </div>

        <nav className="cov-filters" aria-label="Filter the checklist">
          <Link href={href({})} aria-current={!filter.kind && !filter.status ? "page" : undefined}>
            All
          </Link>
          {KINDS.map((k) => (
            <Link
              key={k.key}
              href={href({ kind: k.key, status: filter.status })}
              aria-current={filter.kind === k.key ? "page" : undefined}
            >
              {k.short}
            </Link>
          ))}
          <span className="cov-sep" aria-hidden="true" />
          {statuses.map((s) => (
            <Link
              key={s}
              href={href({ kind: filter.kind, status: s })}
              aria-current={filter.status === s ? "page" : undefined}
            >
              {s}
            </Link>
          ))}
        </nav>

        <div className="cov-table-wrap">
          <table className="cov-table">
            <caption className="sr-only">Platform coverage</caption>
            <thead>
              <tr>
                <th scope="col">Platform</th>
                <th scope="col">Type</th>
                <th scope="col">Status</th>
                <th scope="col">Live now</th>
                <th scope="col">Boards ok / total</th>
                <th scope="col">Open jobs</th>
                <th scope="col">Runs 7d ok / failed</th>
                <th scope="col" title="Share of open jobs with a description, a resolved country, a posted date and a stated salary">
                  Description · Place · Date · Pay
                </th>
                <th scope="col">Last success</th>
                <th scope="col">Notes</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.slug}>
                  <th scope="row">{r.name}</th>
                  <td>{r.kind === "ats" ? "ATS" : "Job board"}</td>
                  <td>
                    <span className={`cov-pill ${STATUS_CLASS[r.status] ?? "other"}`}>{r.status}</span>
                  </td>
                  <td>
                    <span className={`cov-pill ${r.live ? "ok" : r.boards_ok_2d > 0 ? "part" : "other"}`}>
                      {r.live ? "Live" : `${r.boards_ok_2d} of ${LIVE_BOARDS}`}
                    </span>
                  </td>
                  <td>{r.boards_total ? `${r.boards_ok_2d} / ${r.boards_total}` : "—"}</td>
                  <td>{r.open_jobs ? formatCount(r.open_jobs) : "—"}</td>
                  <td>{r.runs_7d_ok + r.runs_7d_failed ? `${r.runs_7d_ok} / ${r.runs_7d_failed}` : "—"}</td>
                  <td className="cov-shares">
                    {[r.with_description, r.with_location, r.with_posted_date, r.with_salary]
                      .map(percent)
                      .join(" · ")}
                  </td>
                  <td>{r.last_success_at ? ageLabel(r.last_success_at) : "—"}</td>
                  <td className="cov-notes">{r.note || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length === 0 && <p className="cov-note">No platforms match this filter.</p>}
        </div>
      </div>
    </section>
  );
}
