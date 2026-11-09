"use client";

import Link from "next/link";
import { useState } from "react";

import styles from "@/components/workspace/workspace.module.css";
import { saveJob, unsaveJob, useSaved } from "@/lib/workspace";

/** Saves a job to the visitor's anonymous workspace; the first click creates the workspace. */
export function SaveButton({ jobId, title }: { jobId: string; title: string }) {
  const { loaded, saved } = useSaved(jobId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      if (saved && saved.stage === "saved") await unsaveJob(jobId, saved.id);
      else if (!saved) await saveJob(jobId);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  if (saved && saved.stage !== "saved") {
    return (
      <Link href="/workspace/tracker" className={`${styles.save} ${styles.saveOn}`}>
        In your tracker: {saved.stage}
      </Link>
    );
  }
  return (
    <>
      <button
        type="button"
        className={saved ? `${styles.save} ${styles.saveOn}` : styles.save}
        onClick={toggle}
        disabled={busy || !loaded}
        aria-pressed={saved !== null}
        aria-label={saved ? `Remove ${title} from your saved jobs` : `Save ${title} to your workspace`}
        title={error ?? undefined}
      >
        {saved ? "✓ Saved" : "☆ Save"}
      </button>
      {error && (
        <span role="alert" className={styles.small}>
          {error}
        </span>
      )}
    </>
  );
}
