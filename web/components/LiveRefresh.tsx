"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

type Refresh = { id: string; boards: number; done: number; new_postings: number; changed_postings: number; finished: boolean };

const POLL_MS = 2000;
const GIVE_UP_MS = 90_000;

/**
 * Asks ERIO to re-read the employer boards behind this search, shows how far it got, and
 * reloads the results whenever a board has found something new. The results already on the page
 * come from the index; this only adds what employers posted in the last minutes.
 */
export function LiveRefresh({ query }: { query: string }) {
  const router = useRouter();
  const [state, setState] = useState<Refresh | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let stopped = false;
    const started = Date.now();
    let reloadedAt = 0;
    setState(null);
    setFailed(false);

    async function poll(id: string) {
      while (!stopped && Date.now() - started < GIVE_UP_MS) {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        if (stopped) return;
        const response = await fetch(`/search/live/${id}`, { cache: "no-store" });
        if (!response.ok) return setFailed(true);
        const next = (await response.json()) as Refresh;
        setState(next);
        // Show what a board found as soon as it has: one slow board never holds the rest back.
        const found = next.new_postings + next.changed_postings;
        if (found > reloadedAt) {
          reloadedAt = found;
          router.refresh();
        }
        if (next.finished) return;
      }
    }

    fetch(`/search/live${query}`, { method: "POST", cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) return setFailed(true);
        const first = (await response.json()) as Refresh;
        if (stopped) return;
        setState(first);
        if (!first.finished) await poll(first.id);
      })
      .catch(() => !stopped && setFailed(true));

    return () => {
      stopped = true;
    };
  }, [query, router]);

  if (failed || !state || state.boards === 0) return null;
  const news = state.new_postings;
  return (
    <span className="live" role="status" aria-live="polite">
      <span className={`live-dot${state.finished ? " live-done" : ""}`} aria-hidden="true" />
      {state.finished
        ? news > 0
          ? `Checked ${state.boards} employer boards · ${news} new job${news === 1 ? "" : "s"} added`
          : `Checked ${state.boards} employer boards · up to date`
        : `Checking ${state.boards} employer boards for new jobs… ${state.done}/${state.boards}`}
    </span>
  );
}
