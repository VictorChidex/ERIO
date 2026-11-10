"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { Gate, useWorkspaceData } from "@/components/workspace/Gate";
import styles from "@/components/workspace/workspace.module.css";
import { ACCENTS, CARDS, type Accent, type Card, type Density, type Prefs, type Profile, saveProfile, START_TABS, type StartTab } from "@/lib/profile";
import { call, copyText, getToken, setToken, type Summary, workspaceLink } from "@/lib/workspace";

type ImportResult = {
  applications_added: number;
  applications_skipped: number;
  searches_added: number;
  searches_skipped: number;
  notes: string[];
};

function Settings() {
  const { data } = useWorkspaceData<Summary>("");
  const [message, setMessage] = useState<string | null>(null);
  const [reveal, setReveal] = useState(false);
  const profile = useWorkspaceData<Profile>("profile");
  const prefs: Prefs = profile.data?.prefs ?? { accent: "default", density: "comfortable", start_tab: "overview", hidden_cards: [] };

  async function look(change: Partial<Prefs>) {
    try {
      await saveProfile({ prefs: { ...prefs, ...change } });
      profile.reload();
      setMessage("Saved. The look applies to this workspace on every device you open it on.");
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : "Could not save");
    }
  }
  const file = useRef<HTMLInputElement>(null);
  const link = typeof window !== "undefined" && getToken() ? workspaceLink(getToken() ?? "") : "";

  async function exportJson() {
    const body = await call<unknown>("GET", "export");
    const blob = new Blob([JSON.stringify(body, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `erio-workspace-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    setMessage("Exported. The file stays on your device.");
  }

  async function importJson(selected: File | undefined) {
    if (!selected) return;
    try {
      const result = await call<ImportResult>("POST", "import", await selected.text());
      setMessage(
        `Imported ${result.applications_added} applications and ${result.searches_added} searches ` +
          `(${result.applications_skipped + result.searches_skipped} skipped). ${result.notes.join(" ")}`,
      );
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : "Could not import");
    } finally {
      if (file.current) file.current.value = "";
    }
  }

  async function deleteAll() {
    if (!window.confirm("Delete your workspace and everything in it? This cannot be undone.")) return;
    try {
      await call<void>("DELETE", "");
      setToken(null);
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : "Could not delete");
    }
  }

  return (
    <div className={styles.stack}>
      <div className={styles.card}>
        <h2>Workspace link</h2>
        <p className={styles.muted}>
          Open this link on another device to continue there. Anyone who has it can open your workspace, so keep it like a
          key. The part after # is never sent to any server, including ERIO.
        </p>
        <div className={styles.row} style={{ marginTop: 10 }}>
          <button type="button" className={styles.ghost} onClick={() => setReveal(!reveal)}>
            {reveal ? "Hide link" : "Show link"}
          </button>
          <button type="button" className={styles.btn} onClick={async () => setMessage((await copyText(link)) ? "Link copied." : "Could not copy.")}>
            Copy link
          </button>
        </div>
        {reveal && <p className={styles.mono} style={{ marginTop: 10 }}>{link}</p>}
        <p className={styles.small} style={{ marginTop: 10 }}>
          Lose the link and clear this browser, and nobody (including ERIO) can recover the workspace. Export a copy now
          and then.
        </p>
      </div>

      <div className={styles.card}>
        <h2>Make it yours</h2>
        <div className={styles.grid} style={{ marginTop: 8 }}>
          <div className={styles.field}>
            Colour
            <div className={styles.row}>
              {(Object.keys(ACCENTS) as Accent[]).map((key) => (
                <button
                  key={key}
                  type="button"
                  className={key === prefs.accent ? styles.btn : styles.ghost}
                  style={ACCENTS[key].color ? { borderColor: ACCENTS[key].color ?? undefined } : undefined}
                  aria-pressed={key === prefs.accent}
                  onClick={() => void look({ accent: key })}
                >
                  {ACCENTS[key].label}
                </button>
              ))}
            </div>
          </div>
          <label className={styles.field}>
            Spacing
            <select className={styles.select} value={prefs.density} onChange={(e) => void look({ density: e.target.value as Density })}>
              <option value="comfortable">Comfortable</option>
              <option value="compact">Compact</option>
            </select>
          </label>
          <label className={styles.field}>
            Open on
            <select className={styles.select} value={prefs.start_tab} onChange={(e) => void look({ start_tab: e.target.value as StartTab })}>
              {START_TABS.map((tab) => (
                <option key={tab.id} value={tab.id}>
                  {tab.label}
                </option>
              ))}
            </select>
          </label>
          <fieldset className={styles.field} style={{ border: 0, padding: 0 }}>
            <legend>Cards on the overview</legend>
            {CARDS.map((card) => (
              <label key={card.id} className={styles.row}>
                <input
                  type="checkbox"
                  checked={!prefs.hidden_cards.includes(card.id)}
                  onChange={(e) =>
                    void look({
                      hidden_cards: e.target.checked
                        ? prefs.hidden_cards.filter((c) => c !== card.id)
                        : ([...prefs.hidden_cards, card.id] as Card[]),
                    })
                  }
                />{" "}
                {card.label}
              </label>
            ))}
          </fieldset>
        </div>
      </div>

      <div className={styles.card}>
        <h2>Export and import</h2>
        <div className={styles.row}>
          <button type="button" className={styles.btn} onClick={() => void exportJson()}>
            Export everything (JSON)
          </button>
          <label className={styles.ghost}>
            Import a file
            <input ref={file} type="file" accept="application/json,.json" hidden onChange={(e) => void importJson(e.target.files?.[0])} />
          </label>
        </div>
        <p className={styles.small} style={{ marginTop: 8 }}>
          Importing adds to this workspace and skips jobs you already saved. CVs are never stored, so none is exported.
        </p>
      </div>

      <div className={styles.card}>
        <h2>Limits</h2>
        <ul className={styles.list}>
          <li>Up to {data?.limits.applications ?? 1000} saved jobs and applications ({data?.limits.saved ?? 500} at the Saved stage)</li>
          <li>Up to {data?.limits.searches ?? 20} saved searches</li>
          <li>Notes up to {(data?.limits.note_bytes ?? 65536) / 1024} KB each</li>
          <li>A workspace unused for {data?.limits.retention_days ?? 365} days is deleted automatically</li>
        </ul>
      </div>

      <div className={styles.card}>
        <h2>Delete everything</h2>
        <p className={styles.muted}>
          Removes this workspace, its saved jobs, notes, timelines, saved searches, feeds, webhooks, CV skills and alert email address from ERIO, for good.
          Your CV text, if you kept it in this browser, is removed on the{" "}
          <Link href="/workspace/cv">CV match page</Link> with “Forget my CV”.
        </p>
        <div className={styles.row} style={{ marginTop: 10 }}>
          <button type="button" className={`${styles.ghost} ${styles.danger}`} onClick={() => void deleteAll()}>
            Delete my workspace
          </button>
        </div>
      </div>
      {message && (
        <p role="status" className={styles.notice}>
          {message}
        </p>
      )}
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Gate>
      <Settings />
    </Gate>
  );
}
