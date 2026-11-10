"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import styles from "@/components/workspace/workspace.module.css";
import { confirmAlerts } from "@/lib/profile";

function Confirm() {
  const token = useSearchParams()?.get("token") ?? "";
  const [state, setState] = useState<"idle" | "busy" | "done" | "failed">("idle");
  const [error, setError] = useState("");

  async function confirm() {
    setState("busy");
    try {
      await confirmAlerts(token);
      setState("done");
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Could not confirm");
      setState("failed");
    }
  }

  // The button is on purpose: mail scanners open links, and opening must not confirm.
  return (
    <div className={styles.card}>
      <h1 style={{ fontSize: 26, marginBottom: 8 }}>Confirm your job alerts</h1>
      {state === "done" ? (
        <p role="status" className={`${styles.notice} ${styles.good}`}>
          Confirmed. ERIO will email you the new jobs that fit your CV. Every email has a link to stop them.{" "}
          <Link href="/workspace/alerts">Back to your workspace</Link>
        </p>
      ) : (
        <>
          <p className={styles.muted}>Press the button to start receiving job matches at the address you gave.</p>
          <div className={styles.row} style={{ marginTop: 12 }}>
            <button type="button" className={styles.btn} disabled={state === "busy" || token.length < 20} onClick={() => void confirm()}>
              {state === "busy" ? "Confirming…" : "Yes, email me matches"}
            </button>
          </div>
          {state === "failed" && (
            <p role="alert" className={`${styles.notice} ${styles.warn}`} style={{ marginTop: 12 }}>
              {error} You can ask for a new link in your workspace under Profile &amp; alerts.
            </p>
          )}
        </>
      )}
    </div>
  );
}

export default function ConfirmPage() {
  return (
    <Suspense fallback={<p className={styles.muted}>Loading…</p>}>
      <Confirm />
    </Suspense>
  );
}
