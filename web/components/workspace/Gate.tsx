"use client";

import { useCallback, useEffect, useState } from "react";

import styles from "@/components/workspace/workspace.module.css";
import { call, createWorkspace, setToken, tokenFromLink, useToken } from "@/lib/workspace";

/** Shows its children once a workspace exists on this device; otherwise offers to make or open one. */
export function Gate({ children }: { children: React.ReactNode }) {
  const token = useToken();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState("");

  if (token === undefined) return <p className={styles.muted}>Loading…</p>;
  if (token) return <>{children}</>;

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await createWorkspace();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Could not create a workspace");
    } finally {
      setBusy(false);
    }
  }

  async function open() {
    const found = tokenFromLink(link);
    if (!found) {
      setError("That does not look like a workspace link.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await call("GET", "", undefined, found);
      setToken(found);
    } catch {
      setError("No workspace was found for that link. It may have been deleted.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.grid}>
      <div className={styles.card}>
        <h2>Start a workspace</h2>
        <p className={styles.muted}>
          One click. No account and no email. Your browser keeps a random key; ERIO stores only a
          fingerprint of it, so ERIO cannot tell who you are, and you can delete everything at any time.
        </p>
        <div className={styles.row} style={{ marginTop: 14 }}>
          <button type="button" className={styles.btn} onClick={create} disabled={busy}>
            Create my workspace
          </button>
        </div>
      </div>
      <div className={styles.card}>
        <h2>Open one you already have</h2>
        <p className={styles.muted}>Paste the workspace link from your other device (Settings, then Workspace link).</p>
        <label className={styles.field} style={{ marginTop: 10 }}>
          Workspace link
          <input className={styles.input} value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://…/workspace#k=…" />
        </label>
        <div className={styles.row} style={{ marginTop: 10 }}>
          <button type="button" className={styles.ghost} onClick={open} disabled={busy || !link}>
            Open workspace
          </button>
        </div>
      </div>
      {error && (
        <p role="alert" className={`${styles.notice} ${styles.bad}`}>
          {error}
        </p>
      )}
    </div>
  );
}

/** Loads data for the current workspace and reloads on demand. */
export function useWorkspaceData<T>(path: string): { data: T | null; error: string | null; reload: () => void } {
  const token = useToken();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    call<T>("GET", path, undefined, token)
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      })
      .catch((problem: Error) => !cancelled && setError(problem.message));
    return () => {
      cancelled = true;
    };
  }, [token, path, tick]);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, reload };
}
