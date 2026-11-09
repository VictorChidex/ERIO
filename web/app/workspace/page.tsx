"use client";

import Link from "next/link";

import { Gate, useWorkspaceData } from "@/components/workspace/Gate";
import styles from "@/components/workspace/workspace.module.css";
import { type Application, type SavedSearch, STAGE_LABELS, STAGES, type Summary } from "@/lib/workspace";

function Overview() {
  const summary = useWorkspaceData<Summary>("");
  const apps = useWorkspaceData<{ data: Application[] }>("applications");
  const searches = useWorkspaceData<SavedSearch[]>("searches");
  const attention = (apps.data?.data ?? []).filter((a) => a.nudge || (a.job && a.job.changes.length > 0));
  const withNew = (searches.data ?? []).filter((s) => s.new_count > 0);
  const error = summary.error ?? apps.error ?? searches.error;

  return (
    <div className={styles.stack}>
      {error && <p className={`${styles.notice} ${styles.bad}`}>{error}</p>}
      <div className={styles.card}>
        <h2>Where things stand</h2>
        <div className={styles.stats}>
          {STAGES.map((stage) => (
            <div key={stage}>
              <div className={styles.stat}>{summary.data?.counts[stage] ?? "–"}</div>
              <div className={styles.small}>{STAGE_LABELS[stage]}</div>
            </div>
          ))}
          <div>
            <div className={styles.stat}>{summary.data?.counts.searches ?? "–"}</div>
            <div className={styles.small}>Saved searches</div>
          </div>
        </div>
      </div>

      <div className={styles.grid}>
        <div className={styles.card}>
          <h3>Needs your attention</h3>
          {attention.length === 0 ? (
            <p className={styles.muted}>Nothing waiting. Saved jobs that close or change, stalled applications and due follow-ups appear here.</p>
          ) : (
            <ul className={styles.list}>
              {attention.slice(0, 8).map((a) => (
                <li key={a.id}>
                  <strong>{a.title}</strong> <span className={styles.muted}>at {a.company}</span>
                  <div className={styles.row}>
                    {a.job?.changes.map((c) => (
                      <span key={c} className={`${styles.flag} ${c === "closed" ? styles.flagRed : ""}`}>
                        Job {c}
                      </span>
                    ))}
                    {a.nudge && <span className={styles.flag}>{a.nudge}</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}
          <p style={{ marginTop: 12 }}>
            <Link href="/workspace/tracker">Open the tracker →</Link>
          </p>
        </div>

        <div className={styles.card}>
          <h3>New since you last looked</h3>
          {withNew.length === 0 ? (
            <p className={styles.muted}>No new matches. Save a search to follow it by feed reader or webhook, with no email.</p>
          ) : (
            <ul className={styles.list}>
              {withNew.map((s) => (
                <li key={s.id}>
                  <strong>{s.new_count}</strong> new for <span>{s.name}</span>
                </li>
              ))}
            </ul>
          )}
          <p style={{ marginTop: 12 }}>
            <Link href="/workspace/searches">Saved searches →</Link>
          </p>
        </div>

        <div className={styles.card}>
          <h3>Compare your CV</h3>
          <p className={styles.muted}>
            Paste your CV to see which open jobs overlap with it and why. It is read once, never stored on ERIO&apos;s
            servers, and never leaves the match request.
          </p>
          <p style={{ marginTop: 12 }}>
            <Link href="/workspace/cv">CV match →</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default function WorkspacePage() {
  return (
    <Gate>
      <Overview />
    </Gate>
  );
}
