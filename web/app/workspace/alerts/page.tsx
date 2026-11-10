"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { SaveButton } from "@/components/SaveButton";
import { Gate, useWorkspaceData } from "@/components/workspace/Gate";
import styles from "@/components/workspace/workspace.module.css";
import {
  askForAlerts,
  COUNTRY_CHOICES,
  findJobs,
  type Pick,
  type Profile,
  saveProfile,
  stopAlerts,
  uploadResume,
} from "@/lib/profile";

const message = (problem: unknown, fallback: string) => (problem instanceof Error ? problem.message : fallback);

function ProfileAndAlerts() {
  const { data: profile, error, reload } = useWorkspaceData<Profile>("profile");
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [picks, setPicks] = useState<Pick[] | null>(null);
  const [title, setTitle] = useState("");
  const [email, setEmail] = useState("");
  const [frequency, setFrequency] = useState<"daily" | "weekly">("daily");
  const file = useRef<HTMLInputElement>(null);

  async function run(work: () => Promise<void>) {
    setBusy(true);
    setProblem(null);
    setNotice(null);
    try {
      await work();
    } catch (failure) {
      setProblem(message(failure, "Something went wrong"));
    } finally {
      setBusy(false);
    }
  }

  const upload = (selected: File | undefined) =>
    selected &&
    run(async () => {
      const found = await uploadResume(selected);
      setNotice(`Read ${found.length} skills from ${selected.name}. The file itself was not kept.`);
      setPicks(null);
      reload();
      if (file.current) file.current.value = "";
    });

  const patch = (change: Parameters<typeof saveProfile>[0]) =>
    run(async () => {
      await saveProfile(change);
      reload();
    });

  if (!profile) return <p className={styles.muted}>{error ?? "Loading…"}</p>;
  const hasSkills = profile.skills.length > 0;
  const mail = profile.mail;

  return (
    <div className={styles.stack}>
      {problem && (
        <p role="alert" className={`${styles.notice} ${styles.warn}`}>
          {problem}
        </p>
      )}
      {notice && (
        <p role="status" className={`${styles.notice} ${styles.good}`}>
          {notice}
        </p>
      )}

      <div className={styles.card}>
        <h2>1. Your CV</h2>
        <p className={styles.muted}>
          Upload a PDF, Word (.docx) or text file. ERIO reads it for skills, tools, licences and languages with a fixed
          word list, keeps <strong>only that list</strong> and throws the file away. You can also{" "}
          <Link href="/workspace/cv">paste text</Link> instead.
        </p>
        <div className={styles.row} style={{ marginTop: 12 }}>
          <input
            ref={file}
            type="file"
            accept=".pdf,.docx,.txt,.md,application/pdf"
            aria-label="Upload your CV"
            disabled={busy}
            onChange={(event) => void upload(event.target.files?.[0])}
          />
        </div>
        {hasSkills ? (
          <>
            <h3 style={{ marginTop: 16 }}>Skills ERIO will match on</h3>
            <ul className={styles.chips}>
              {profile.skills.map((skill) => (
                <li key={skill.id} className={styles.chip}>
                  {skill.label}{" "}
                  <button
                    type="button"
                    aria-label={`Remove ${skill.label}`}
                    disabled={busy}
                    onClick={() => void patch({ skills: profile.skills.filter((s) => s.id !== skill.id).map((s) => s.id) })}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
            <p className={styles.small} style={{ marginTop: 8 }}>
              Remove anything that is not really you. Matches and emails use exactly this list.
            </p>
          </>
        ) : (
          <p className={styles.small} style={{ marginTop: 10 }}>
            No skills yet. Upload a CV to begin.
          </p>
        )}
      </div>

      <div className={styles.card}>
        <h2>2. What you are looking for</h2>
        <div className={styles.grid} style={{ marginTop: 8 }}>
          <div className={styles.field}>
            Job titles (up to 5)
            <ul className={styles.chips}>
              {profile.titles.map((t) => (
                <li key={t} className={styles.chip}>
                  {t}{" "}
                  <button
                    type="button"
                    aria-label={`Remove ${t}`}
                    onClick={() => void patch({ titles: profile.titles.filter((x) => x !== t) })}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
            <form
              className={styles.row}
              onSubmit={(event) => {
                event.preventDefault();
                const next = title.trim();
                if (next.length < 2) return;
                setTitle("");
                void patch({ titles: [...profile.titles, next].slice(0, 5) });
              }}
            >
              <input
                className={styles.input}
                style={{ flex: 1 }}
                value={title}
                maxLength={80}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="e.g. Backend developer"
              />
              <button type="submit" className={styles.ghost} disabled={busy || profile.titles.length >= 5}>
                Add
              </button>
            </form>
          </div>
          <label className={styles.field}>
            Where (hold Ctrl or Cmd to pick several; none means anywhere)
            <select
              className={styles.select}
              multiple
              size={6}
              value={profile.countries}
              onChange={(event) =>
                void patch({ countries: Array.from(event.target.selectedOptions, (option) => option.value) })
              }
            >
              {COUNTRY_CHOICES.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <div className={styles.field}>
            <label className={styles.row}>
              <input
                type="checkbox"
                checked={profile.remote_only}
                onChange={(event) => void patch({ remote_only: event.target.checked })}
              />{" "}
              Remote jobs only
            </label>
            <label className={styles.field} style={{ marginTop: 10 }}>
              Only show jobs that match at least {profile.min_score}%
              <input
                type="range"
                min={10}
                max={90}
                step={5}
                defaultValue={profile.min_score}
                onMouseUp={(event) => void patch({ min_score: Number(event.currentTarget.value) })}
                onKeyUp={(event) => void patch({ min_score: Number(event.currentTarget.value) })}
              />
            </label>
          </div>
        </div>
      </div>

      <div className={styles.card}>
        <h2>3. Jobs found for you</h2>
        <p className={styles.muted}>Open jobs from the last 30 days, ranked by how much of each job&apos;s requirements your skills cover.</p>
        <div className={styles.row} style={{ marginTop: 10 }}>
          <button
            type="button"
            className={styles.btn}
            disabled={busy || !hasSkills}
            onClick={() =>
              void run(async () => {
                const found = await findJobs();
                setPicks(found.filter((p) => p.score >= profile.min_score));
              })
            }
          >
            Find jobs for me
          </button>
        </div>
        {picks && picks.length === 0 && <p className={styles.notice} style={{ marginTop: 10 }}>Nothing new fits right now. Try lowering the match level or adding skills.</p>}
        {picks && picks.length > 0 && (
          <ul className={styles.list} style={{ marginTop: 12 }}>
            {picks.map((pick) => (
              <li key={pick.job_id} className={styles.item}>
                <div className={styles.spread}>
                  <div>
                    <div className={styles.itemTitle}>
                      <Link href={`/jobs/${pick.job_id}`}>{pick.title}</Link>
                    </div>
                    <p className={styles.muted}>
                      {pick.company}
                      {pick.location ? ` · ${pick.location}` : ""}
                    </p>
                  </div>
                  <div className={styles.row}>
                    <strong>{pick.score}%</strong>
                    <SaveButton jobId={pick.job_id} title={pick.title} />
                    <a className={styles.ghost} href={pick.apply_url} target="_blank" rel="noopener noreferrer nofollow">
                      Apply
                    </a>
                  </div>
                </div>
                <p className={styles.small}>{pick.why}</p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className={styles.card}>
        <h2>4. Email me new matches</h2>
        <p className={styles.muted}>
          ERIO emails you the new jobs that fit your skills, best first, never the same job twice. Nothing is sent until you
          open the confirmation link, every email has a stop link, and ERIO never applies for you.
        </p>
        {mail ? (
          <div style={{ marginTop: 12 }}>
            <p className={`${styles.notice} ${mail.confirmed ? styles.good : styles.warn}`}>
              {mail.confirmed
                ? `Alerts go to ${mail.email}, ${mail.frequency}${mail.paused ? " (paused)" : ""}.`
                : `We sent a confirmation link to ${mail.email}. Alerts start once you open it (it works for 48 hours).`}
            </p>
            <div className={styles.row} style={{ marginTop: 10 }}>
              <button
                type="button"
                className={`${styles.ghost} ${styles.danger}`}
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await stopAlerts();
                    setNotice("Alerts stopped and your address deleted.");
                    reload();
                  })
                }
              >
                Stop alerts and delete my address
              </button>
            </div>
          </div>
        ) : (
          <form
            className={styles.row}
            style={{ marginTop: 12 }}
            onSubmit={(event) => {
              event.preventDefault();
              void run(async () => {
                await askForAlerts(email, frequency);
                setNotice("Check your inbox for the confirmation link.");
                reload();
              });
            }}
          >
            <input
              className={styles.input}
              style={{ flex: 1, minWidth: 220 }}
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              aria-label="Your email address"
            />
            <select
              className={styles.select}
              style={{ width: "auto" }}
              value={frequency}
              onChange={(event) => setFrequency(event.target.value as "daily" | "weekly")}
              aria-label="How often"
            >
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
            </select>
            <button type="submit" className={styles.btn} disabled={busy || !hasSkills}>
              Send confirmation
            </button>
          </form>
        )}
        {!hasSkills && !mail && <p className={styles.small} style={{ marginTop: 8 }}>Upload your CV first so ERIO knows what to look for.</p>}
      </div>
    </div>
  );
}

export default function AlertsPage() {
  return (
    <Gate>
      <ProfileAndAlerts />
    </Gate>
  );
}
