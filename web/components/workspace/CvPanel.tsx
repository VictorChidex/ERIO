"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import styles from "@/components/workspace/workspace.module.css";
import { call, copyText, type JobMatch, useCvSkills } from "@/lib/workspace";

/** "Requirements vs your CV" on a job page. The CV stays in this browser; only skill ids travel. */
export function CvPanel({ jobId }: { jobId: string }) {
  const skills = useCvSkills();
  const key = skills.join(",");
  const [match, setMatch] = useState<JobMatch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    call<JobMatch>("POST", `match/job/${encodeURIComponent(jobId)}`, { skills: key.split(",") })
      .then((result) => !cancelled && setMatch(result))
      .catch((problem: Error) => !cancelled && setError(problem.message));
    return () => {
      cancelled = true;
    };
  }, [jobId, key]);

  return (
    <section className={styles.panel} aria-labelledby="cvpanel-title">
      <div className="wrap">
        <div className={styles.card}>
          <h2 id="cvpanel-title">Requirements vs your CV</h2>
          {!key && (
            <p className={styles.muted}>
              Paste your CV on the <Link href="/workspace/cv">CV match page</Link> to see which of this job&apos;s
              requirements you already cover. Your CV stays in this browser; ERIO never stores it.
            </p>
          )}
          {error && <p className={styles.notice}>{error}</p>}
          {match && (
            <div className={styles.stack}>
              <p>
                <strong>{match.score}% overlap.</strong> <span className={styles.muted}>{match.explanation}</span>
              </p>
              {match.required.length === 0 ? (
                <p className={styles.muted}>No licences, tools or skills could be recognised in this posting.</p>
              ) : (
                <ul className={styles.chips} aria-label="Requirements">
                  {match.required.map((tag) => {
                    const have = match.matched.some((m) => m.id === tag.id);
                    return (
                      <li key={tag.id} className={`${styles.chip} ${have ? styles.chipOk : styles.chipGap}`}>
                        {have ? "✓ " : "○ "}
                        {tag.label}
                      </li>
                    );
                  })}
                </ul>
              )}
              <div className={styles.row}>
                <button
                  type="button"
                  className={styles.btn}
                  onClick={async () => setCopied(await copyText(match.kit))}
                >
                  {copied ? "Copied" : "Copy apply kit"}
                </button>
                <span className={styles.small}>
                  A plain-text checklist and cover-note outline. ERIO never applies for you.
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
