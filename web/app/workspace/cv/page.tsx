"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { SaveButton } from "@/components/SaveButton";
import styles from "@/components/workspace/workspace.module.css";
import {
  call,
  getCvText,
  type RankedJob,
  setCvSkills,
  setCvText,
  type SkillTag,
  WorkspaceError,
} from "@/lib/workspace";

type Result = { skills: SkillTag[]; data: RankedJob[]; meta: { candidates: number; matched: number } };

export default function CvMatchPage() {
  const [text, setText] = useState("");
  const [remember, setRemember] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const saved = getCvText();
    if (saved) {
      setText(saved);
      setRemember(true);
    }
  }, []);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const found = await call<Result>("POST", "match", { cv_text: text, limit: 25 });
      setResult(found);
      setCvSkills(found.skills.map((s) => s.id));
      setCvText(remember ? text : null);
    } catch (problem) {
      setResult(null);
      setError(problem instanceof WorkspaceError ? problem.message : "Could not match");
    } finally {
      setBusy(false);
    }
  }

  function forget() {
    setText("");
    setResult(null);
    setRemember(false);
    setCvText(null);
    setCvSkills(null);
  }

  return (
    <div className={styles.stack}>
      <div className={styles.card}>
        <h2>Compare your CV with open jobs</h2>
        <p className={styles.muted}>
          ERIO reads your CV for skills, tools, licences and languages with a fixed word list (no AI model), then ranks
          jobs by how much of what they ask for you cover, and says why. Your CV is sent for this one request and
          never stored or logged on ERIO&apos;s servers. ERIO never applies for you.
        </p>
        <label className={styles.field} style={{ marginTop: 12 }}>
          Paste your CV text
          <textarea className={styles.textarea} style={{ minHeight: 220 }} value={text} onChange={(e) => setText(e.target.value)} maxLength={30000} />
        </label>
        <div className={styles.row} style={{ marginTop: 12 }}>
          <button type="button" className={styles.btn} disabled={busy || text.trim().length < 20} onClick={() => void run()}>
            {busy ? "Matching…" : "Find matching jobs"}
          </button>
          <label className={styles.small}>
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Keep my CV in this
            browser (never on ERIO)
          </label>
          <button type="button" className={`${styles.ghost} ${styles.danger}`} onClick={forget}>
            Forget my CV
          </button>
        </div>
        {error && (
          <p role="alert" className={`${styles.notice} ${styles.warn}`} style={{ marginTop: 12 }}>
            {error}
          </p>
        )}
      </div>

      {result && (
        <>
          <div className={styles.card}>
            <h3>Skills ERIO found in your CV</h3>
            <ul className={styles.chips}>
              {result.skills.map((s) => (
                <li key={s.id} className={styles.chip}>
                  {s.label}
                </li>
              ))}
            </ul>
            <p className={styles.small} style={{ marginTop: 8 }}>
              Missing something? Write it the way job ads do (for example “Registered Nurse”, “Class A CDL”, “IFRS”).
              Job pages now show “Requirements vs your CV” using these skills.
            </p>
          </div>
          {result.data.length === 0 ? (
            <p className={styles.notice}>No open job overlapped with those skills right now.</p>
          ) : (
            <ul className={styles.list}>
              {result.data.map((row) => (
                <li key={row.job.canonical_id} className={styles.card}>
                  <div className={styles.spread}>
                    <div>
                      <h3>
                        <Link href={`/jobs/${row.job.canonical_id}`}>{row.job.title}</Link>
                      </h3>
                      <p className={styles.muted}>
                        {row.job.company.name}
                        {row.job.location_text ? ` · ${row.job.location_text}` : ""}
                      </p>
                    </div>
                    <div className={styles.row}>
                      <strong>{row.score}%</strong>
                      <SaveButton jobId={row.job.canonical_id} title={row.job.title} />
                    </div>
                  </div>
                  <div className={styles.score} role="img" aria-label={`${row.score}% overlap`}>
                    <span style={{ width: `${row.score}%` }} />
                  </div>
                  <p className={styles.muted} style={{ marginTop: 8 }}>
                    {row.explanation}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
