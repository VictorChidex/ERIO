"use client";

import Link from "next/link";
import { useState } from "react";

import { Gate, useWorkspaceData } from "@/components/workspace/Gate";
import styles from "@/components/workspace/workspace.module.css";
import {
  type Application,
  call,
  copyText,
  type JobMatch,
  type Stage,
  STAGE_LABELS,
  STAGES,
  useCvSkills,
} from "@/lib/workspace";

function day(iso: string): string {
  return new Date(iso).toISOString().slice(0, 10);
}

function Card({ app, reload }: { app: Application; reload: () => void }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<Application | null>(null);
  const [notes, setNotes] = useState(app.notes);
  const [entry, setEntry] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const skills = useCvSkills();

  async function act(work: () => Promise<unknown>, ok?: string) {
    setMessage(null);
    try {
      await work();
      if (ok) setMessage(ok);
      reload();
      if (open) setDetail(await call<Application>("GET", `applications/${app.id}`));
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : "Something went wrong");
    }
  }

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next) setDetail(await call<Application>("GET", `applications/${app.id}`));
  }

  async function kit() {
    if (!app.job_id) return;
    if (skills.length === 0) {
      setMessage("Paste your CV on the CV match page first, so the kit can use your skills.");
      return;
    }
    const match = await call<JobMatch>("POST", `match/job/${encodeURIComponent(app.job_id)}`, { skills });
    setMessage((await copyText(match.kit)) ? "Apply kit copied." : "Could not copy; your browser blocked it.");
  }

  const patch = (body: Record<string, unknown>, ok?: string) => act(() => call("PATCH", `applications/${app.id}`, body), ok);

  return (
    <article className={styles.item}>
      <div className={styles.itemTitle}>
        {app.job_id ? <Link href={`/jobs/${app.job_id}`}>{app.title}</Link> : app.title}
      </div>
      <div className={styles.muted}>
        {app.company}
        {app.location ? ` · ${app.location}` : ""}
      </div>
      <div className={styles.row}>
        {app.job?.changes.map((change) => (
          <span key={change} className={`${styles.flag} ${change === "closed" ? styles.flagRed : ""}`}>
            Job {change}
          </span>
        ))}
        {app.nudge && <span className={styles.flag}>{app.nudge}</span>}
        {app.follow_up_on && <span className={styles.small}>Follow up {app.follow_up_on}</span>}
      </div>
      <label className={styles.field}>
        <span className={styles.small}>Move to</span>
        <select
          className={styles.select}
          value={app.stage}
          onChange={(e) => void patch({ stage: e.target.value as Stage })}
          aria-label={`Stage of ${app.title}`}
        >
          {STAGES.map((stage) => (
            <option key={stage} value={stage}>
              {STAGE_LABELS[stage]}
            </option>
          ))}
        </select>
      </label>
      <div className={styles.row}>
        <button type="button" className={styles.ghost} onClick={toggle} aria-expanded={open}>
          {open ? "Hide details" : "Notes and timeline"}
        </button>
        {app.job_id && (
          <button type="button" className={styles.ghost} onClick={() => void kit()}>
            Apply kit
          </button>
        )}
        {app.url && (
          <a className={styles.ghost} href={app.url} target="_blank" rel="noopener noreferrer nofollow">
            Apply page ↗
          </a>
        )}
      </div>
      {message && (
        <p role="status" className={styles.small}>
          {message}
        </p>
      )}
      {open && (
        <div className={styles.details}>
          {app.job && app.job.changes.length > 0 && (
            <button type="button" className={styles.ghost} onClick={() => void act(() => call("POST", `applications/${app.id}/ack`))}>
              Got it: mark the change as seen
            </button>
          )}
          <label className={styles.field}>
            Notes
            <textarea className={styles.textarea} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={65536} />
          </label>
          <div className={styles.row}>
            <button type="button" className={styles.btn} disabled={notes === app.notes} onClick={() => void patch({ notes }, "Notes saved.")}>
              Save notes
            </button>
          </div>
          <div className={styles.row}>
            <label className={styles.field}>
              Applied on
              <input
                className={styles.input}
                type="date"
                defaultValue={app.applied_on ?? ""}
                onChange={(e) => e.target.value && void patch({ applied_on: e.target.value })}
              />
            </label>
            <label className={styles.field}>
              Follow up on
              <input
                className={styles.input}
                type="date"
                defaultValue={app.follow_up_on ?? ""}
                onChange={(e) => e.target.value && void patch({ follow_up_on: e.target.value })}
              />
            </label>
            {app.follow_up_on && (
              <button type="button" className={styles.ghost} onClick={() => void patch({ clear_follow_up: true })}>
                Clear reminder
              </button>
            )}
          </div>
          <form
            className={styles.row}
            onSubmit={(e) => {
              e.preventDefault();
              if (!entry.trim()) return;
              void act(() => call("POST", `applications/${app.id}/events`, { text: entry }));
              setEntry("");
            }}
          >
            <input className={styles.input} style={{ flex: 1 }} value={entry} onChange={(e) => setEntry(e.target.value)} placeholder="Add to the timeline: recruiter called…" maxLength={2000} aria-label="Timeline entry" />
            <button type="submit" className={styles.ghost}>
              Add
            </button>
          </form>
          <ul className={styles.timeline} aria-label="Timeline">
            {(detail?.events ?? []).map((event) => (
              <li key={event.id}>
                <time dateTime={event.at}>{day(event.at)}</time>
                {event.kind === "stage" && `Moved to ${STAGE_LABELS[event.stage as Stage] ?? event.stage}`}
                {event.kind === "created" && "Saved"}
                {event.kind !== "stage" && event.kind !== "created" && (event.text ?? event.kind)}
              </li>
            ))}
          </ul>
          <button
            type="button"
            className={`${styles.ghost} ${styles.danger}`}
            onClick={() => {
              if (window.confirm("Remove this from your workspace?")) void act(() => call("DELETE", `applications/${app.id}`));
            }}
          >
            Remove
          </button>
        </div>
      )}
    </article>
  );
}

function AddForm({ done }: { done: () => void }) {
  const [form, setForm] = useState({ title: "", company: "", url: "", stage: "applied" as Stage });
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className={styles.card}
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        try {
          await call("POST", "applications", { ...form, url: form.url || undefined });
          setForm({ title: "", company: "", url: "", stage: "applied" });
          done();
        } catch (problem) {
          setError(problem instanceof Error ? problem.message : "Could not add");
        }
      }}
    >
      <h3>Add an application made elsewhere</h3>
      <div className={styles.grid}>
        <label className={styles.field}>
          Job title
          <input className={styles.input} required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} maxLength={300} />
        </label>
        <label className={styles.field}>
          Employer
          <input className={styles.input} required value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} maxLength={300} />
        </label>
        <label className={styles.field}>
          Link (optional)
          <input className={styles.input} type="url" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
        </label>
        <label className={styles.field}>
          Stage
          <select className={styles.select} value={form.stage} onChange={(e) => setForm({ ...form, stage: e.target.value as Stage })}>
            {STAGES.map((stage) => (
              <option key={stage} value={stage}>
                {STAGE_LABELS[stage]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className={styles.row} style={{ marginTop: 12 }}>
        <button type="submit" className={styles.btn}>
          Add
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

function Board() {
  const { data, error, reload } = useWorkspaceData<{ data: Application[] }>("applications");
  const apps = data?.data ?? [];
  return (
    <div className={styles.stack}>
      {error && <p className={`${styles.notice} ${styles.bad}`}>{error}</p>}
      {data && apps.length === 0 && (
        <p className={styles.notice}>
          Nothing here yet. Use <strong>☆ Save</strong> on any job, or add an application you made elsewhere below.
        </p>
      )}
      <div className={styles.board}>
        {STAGES.map((stage) => {
          const column = apps.filter((a) => a.stage === stage);
          return (
            <section key={stage} className={styles.col} aria-label={STAGE_LABELS[stage]}>
              <div className={styles.colHead}>
                <span>{STAGE_LABELS[stage]}</span>
                <span>{column.length}</span>
              </div>
              {column.map((app) => (
                <Card key={`${app.id}-${app.updated_at}`} app={app} reload={reload} />
              ))}
            </section>
          );
        })}
      </div>
      <AddForm done={reload} />
    </div>
  );
}

export default function TrackerPage() {
  return (
    <Gate>
      <Board />
    </Gate>
  );
}
