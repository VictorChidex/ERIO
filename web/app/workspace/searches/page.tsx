"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Gate, useWorkspaceData } from "@/components/workspace/Gate";
import styles from "@/components/workspace/workspace.module.css";
import { ROLE_LABELS } from "@/lib/format";
import { call, copyText, type SavedSearch, type SearchMatch } from "@/lib/workspace";

function describe(params: Record<string, unknown>): string {
  const parts: string[] = [];
  if (params.q) parts.push(`“${String(params.q)}”`);
  for (const key of ["country", "role", "remote_status"]) {
    const value = params[key];
    if (Array.isArray(value) && value.length) parts.push(value.join(", "));
  }
  if (params.salary_min_usd) parts.push(`from $${String(params.salary_min_usd)}`);
  return parts.join(" · ") || "every job";
}

function searchHref(params: Record<string, unknown>): string {
  const query = new URLSearchParams();
  if (params.q) query.set("q", String(params.q));
  const list = (key: string) => (Array.isArray(params[key]) ? (params[key] as string[]).join(",") : "");
  if (list("country")) query.set("country", list("country"));
  if (list("role")) query.set("role", list("role"));
  if (list("remote_status")) query.set("remote_status", list("remote_status"));
  if (params.salary_min_usd) query.set("salary_min_usd", String(params.salary_min_usd));
  return `/search?${query.toString()}`;
}

function SearchCard({ search, reload }: { search: SavedSearch; reload: () => void }) {
  const [matches, setMatches] = useState<SearchMatch[] | null>(null);
  const [hook, setHook] = useState(search.webhook_url ?? "");
  const [message, setMessage] = useState<string | null>(null);
  const feed = `${typeof window === "undefined" ? "" : window.location.origin}/workspace/feed/${search.feed_token}.atom`;

  async function run(work: () => Promise<unknown>, ok?: string) {
    setMessage(null);
    try {
      await work();
      if (ok) setMessage(ok);
      reload();
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : "Something went wrong");
    }
  }

  async function show() {
    setMatches(await call<SearchMatch[]>("GET", `searches/${search.id}/matches`));
    await call("POST", `searches/${search.id}/seen`);
    reload();
  }

  return (
    <article className={styles.card}>
      <div className={styles.spread}>
        <div>
          <h3>
            {search.name}{" "}
            {search.new_count > 0 && <span className="b b-acc">{search.new_count} new</span>}
          </h3>
          <p className={styles.muted}>{describe(search.params)}</p>
        </div>
        <div className={styles.row}>
          <Link className={styles.ghost} href={searchHref(search.params)}>
            Run search
          </Link>
          <button type="button" className={styles.ghost} onClick={() => void show()}>
            Show matches
          </button>
        </div>
      </div>

      {matches && (
        <ul className={styles.list} style={{ marginTop: 12 }}>
          {matches.length === 0 && <li className={styles.muted}>No matches yet.</li>}
          {matches.map((m) => (
            <li key={m.job_id}>
              <Link href={`/jobs/${m.job_id}`}>{m.title}</Link> <span className={styles.muted}>at {m.company}</span>
              {m.is_new && <span className="b b-acc" style={{ marginLeft: 6 }}>new</span>}
            </li>
          ))}
        </ul>
      )}

      <div className={styles.stack} style={{ marginTop: 14 }}>
        <div>
          <div className={styles.small}>Atom feed (any feed reader can follow this address; keep it to yourself)</div>
          <div className={styles.row}>
            <span className={styles.mono}>{feed}</span>
            <button type="button" className={styles.ghost} onClick={async () => setMessage((await copyText(feed)) ? "Feed address copied." : "Could not copy.")}>
              Copy
            </button>
          </div>
        </div>
        <div className={styles.row}>
          <label className={styles.field} style={{ flex: 1, minWidth: 240 }}>
            Webhook (optional, https only; ERIO posts new matches as JSON)
            <input className={styles.input} type="url" value={hook} onChange={(e) => setHook(e.target.value)} placeholder="https://example.com/hooks/jobs" />
          </label>
          <button type="button" className={styles.ghost} disabled={!hook || hook === search.webhook_url} onClick={() => void run(() => call("PATCH", `searches/${search.id}`, { webhook_url: hook }), "Webhook saved.")}>
            Save webhook
          </button>
          {search.webhook_url && (
            <>
              <button type="button" className={styles.ghost} onClick={() => void run(async () => {
                const result = await call<{ ok: boolean; status: number | null; error: string | null }>("POST", `searches/${search.id}/test-webhook`);
                setMessage(result.ok ? "Test delivered." : `Test failed: ${result.error ?? `status ${result.status}`}`);
              })}>
                Send test
              </button>
              <button type="button" className={styles.ghost} onClick={() => void run(() => call("PATCH", `searches/${search.id}`, { clear_webhook: true }), "Webhook removed.")}>
                Remove
              </button>
            </>
          )}
        </div>
        {search.webhook_disabled && (
          <p className={`${styles.notice} ${styles.warn}`}>
            This webhook was switched off after {search.webhook_failures} failed deliveries. Save it again to turn it back on.
          </p>
        )}
        {message && (
          <p role="status" className={styles.small}>
            {message}
          </p>
        )}
        <div className={styles.row}>
          <button type="button" className={`${styles.ghost} ${styles.danger}`} onClick={() => window.confirm("Delete this saved search and its feed?") && void run(() => call("DELETE", `searches/${search.id}`))}>
            Delete search
          </button>
        </div>
      </div>
    </article>
  );
}

function CreateForm({ done }: { done: () => void }) {
  const query = useSearchParams();
  const [name, setName] = useState(query?.get("q") ?? "");
  const [q, setQ] = useState(query?.get("q") ?? "");
  const [country, setCountry] = useState(query?.get("country") ?? "");
  const [role, setRole] = useState(query?.get("role") ?? "");
  const [remote, setRemote] = useState(query?.get("remote_status") ?? "");
  const [salary, setSalary] = useState(query?.get("salary_min_usd") ?? "");
  const [webhook, setWebhook] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <form
      className={styles.card}
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        const params: Record<string, unknown> = {};
        if (q.trim()) params.q = q.trim();
        const codes = country.split(/[ ,]+/).map((c) => c.trim().toUpperCase()).filter(Boolean);
        if (codes.length) params.country = codes;
        if (role) params.role = [role];
        if (remote) params.remote_status = [remote];
        if (salary) params.salary_min_usd = Number(salary);
        try {
          await call("POST", "searches", { name: name.trim() || q.trim() || "My search", params, webhook_url: webhook || undefined });
          setName("");
          setQ("");
          setWebhook("");
          done();
        } catch (problem) {
          setError(problem instanceof Error ? problem.message : "Could not save");
        } finally {
          setBusy(false);
        }
      }}
    >
      <h3>Save a search</h3>
      <p className={styles.muted}>
        ERIO checks it every 10 minutes. You get a counter here and a feed address; no email is ever sent.
      </p>
      <div className={styles.grid} style={{ marginTop: 12 }}>
        <label className={styles.field}>
          Name
          <input className={styles.input} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
        </label>
        <label className={styles.field}>
          Words
          <input className={styles.input} value={q} onChange={(e) => setQ(e.target.value)} maxLength={200} placeholder="nurse, forklift, python…" />
        </label>
        <label className={styles.field}>
          Countries (codes, e.g. NG, GB)
          <input className={styles.input} value={country} onChange={(e) => setCountry(e.target.value)} />
        </label>
        <label className={styles.field}>
          Kind of work
          <select className={styles.select} value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">Any</option>
            {Object.entries(ROLE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          Where
          <select className={styles.select} value={remote} onChange={(e) => setRemote(e.target.value)}>
            <option value="">Any</option>
            <option value="remote">Remote</option>
            <option value="hybrid">Hybrid</option>
            <option value="onsite">On-site</option>
          </select>
        </label>
        <label className={styles.field}>
          Minimum yearly pay (USD)
          <input className={styles.input} type="number" min={0} value={salary} onChange={(e) => setSalary(e.target.value)} />
        </label>
        <label className={styles.field}>
          Webhook (optional)
          <input className={styles.input} type="url" value={webhook} onChange={(e) => setWebhook(e.target.value)} placeholder="https://…" />
        </label>
      </div>
      <div className={styles.row} style={{ marginTop: 12 }}>
        <button type="submit" className={styles.btn} disabled={busy}>
          Save search
        </button>
        {error && (
          <span role="alert" className={styles.small}>
            {error}
          </span>
        )}
      </div>
    </form>
  );
}

function Searches() {
  const { data, error, reload } = useWorkspaceData<SavedSearch[]>("searches");
  return (
    <div className={styles.stack}>
      {error && <p className={`${styles.notice} ${styles.bad}`}>{error}</p>}
      <Suspense fallback={null}>
        <CreateForm done={reload} />
      </Suspense>
      {data?.map((search) => <SearchCard key={`${search.id}-${search.new_count}-${search.webhook_url}-${search.webhook_disabled}`} search={search} reload={reload} />)}
    </div>
  );
}

export default function SearchesPage() {
  return (
    <Gate>
      <Searches />
    </Gate>
  );
}
