"use client";

import { useState } from "react";

import { JobCard } from "@/components/JobCard";
import type { JobRecord } from "@/lib/api";

/** Appends the next page of results; the first page is server-rendered. */
export function LoadMore({
  query,
  cursor,
  countryNames,
  countryFiltered,
  shown,
  total,
}: {
  query: string;
  cursor: string;
  countryNames: Record<string, string>;
  countryFiltered: boolean;
  shown: number;
  total: number;
}) {
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [next, setNext] = useState<string | null>(cursor);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");

  async function load() {
    if (!next) return;
    setState("loading");
    const params = new URLSearchParams(query.replace(/^\?/, ""));
    params.set("cursor", next);
    try {
      const response = await fetch(`/search/more?${params.toString()}`);
      if (!response.ok) throw new Error(String(response.status));
      const page = (await response.json()) as { data: JobRecord[]; next_cursor: string | null };
      setJobs((current) => [...current, ...page.data]);
      setNext(page.next_cursor);
      setState("idle");
    } catch {
      setState("error");
    }
  }

  const showing = shown + jobs.length;
  return (
    <>
      {jobs.length > 0 && (
        <div className="jg jg-more" role="list" aria-label="More jobs">
          {jobs.map((job) => (
            <JobCard
              key={job.canonical_id}
              job={job}
              countryNames={countryNames}
              openToYou={countryFiltered && job.remote_scope === "worldwide"}
            />
          ))}
        </div>
      )}
      <div className="load-more-wrap">
        {next && (
          <button type="button" className="btn-ghost load-more" onClick={load} disabled={state === "loading"}>
            {state === "loading" ? "Loading…" : "Load more jobs"}
          </button>
        )}
        <p className="load-hint" role="status">
          {state === "error" ? "Could not load more jobs. Try again." : `Showing ${showing} of ${total}`}
        </p>
      </div>
    </>
  );
}
