"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import styles from "@/components/workspace/workspace.module.css";
import { type AlertState, alertState, changeAlerts, deleteAlerts } from "@/lib/profile";

export default function ManageAlertsPage() {
  const token = String(useParams()?.token ?? "");
  const [state, setState] = useState<AlertState | null>(null);
  const [gone, setGone] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setState(await alertState(token));
    } catch {
      setGone(true);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function change(patch: { paused?: boolean; frequency?: "daily" | "weekly" }, done: string) {
    try {
      setState(await changeAlerts(token, patch));
      setMessage(done);
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : "Could not save");
    }
  }

  async function remove() {
    try {
      await deleteAlerts(token);
      setState(null);
      setGone(true);
      setMessage("Your address was deleted and the emails have stopped.");
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : "Could not delete");
    }
  }

  return (
    <div className={styles.card}>
      <h1 style={{ fontSize: 26, marginBottom: 8 }}>Your ERIO job alerts</h1>
      {gone && !state ? (
        <p className={styles.notice}>{message ?? "This link is no longer valid: the alerts were already deleted."}</p>
      ) : !state ? (
        <p className={styles.muted}>Loading…</p>
      ) : (
        <>
          <p className={styles.muted}>
            Emails go to <strong>{state.email}</strong>, {state.frequency}
            {state.paused ? ", currently paused" : ""}
            {state.confirmed ? "" : " (not confirmed yet, so nothing is sent)"}.
          </p>
          <div className={styles.row} style={{ marginTop: 14 }}>
            <button
              type="button"
              className={styles.btn}
              onClick={() => void change({ paused: !state.paused }, state.paused ? "Alerts resumed." : "Alerts paused.")}
            >
              {state.paused ? "Resume alerts" : "Pause alerts"}
            </button>
            <button
              type="button"
              className={styles.ghost}
              onClick={() =>
                void change(
                  { frequency: state.frequency === "daily" ? "weekly" : "daily" },
                  `Now ${state.frequency === "daily" ? "weekly" : "daily"}.`,
                )
              }
            >
              Switch to {state.frequency === "daily" ? "weekly" : "daily"}
            </button>
            <button type="button" className={`${styles.ghost} ${styles.danger}`} onClick={() => void remove()}>
              Stop and delete my address
            </button>
          </div>
          {message && (
            <p role="status" className={styles.notice} style={{ marginTop: 12 }}>
              {message}
            </p>
          )}
        </>
      )}
      <p className={styles.small} style={{ marginTop: 16 }}>
        <Link href="/workspace/privacy">How ERIO handles your data</Link>
      </p>
    </div>
  );
}
