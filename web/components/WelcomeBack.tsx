"use client";

import Link from "next/link";

import { useWorkspaceData } from "@/components/workspace/Gate";
import type { Profile } from "@/lib/profile";
import { type Application, type SavedSearch, useToken } from "@/lib/workspace";

type Item = { href: string; figure: string; label: string; hot?: boolean };

/**
 * For a visitor who already has a workspace: what changed since they last looked, in one row
 * at the top of the home page. A first-time visitor sees nothing here (no token, no request).
 */
export function WelcomeBack() {
  const token = useToken();
  if (!token) return null;
  return <Strip />;
}

function Strip() {
  const searches = useWorkspaceData<SavedSearch[]>("searches");
  const apps = useWorkspaceData<{ data: Application[] }>("applications");
  const profile = useWorkspaceData<Profile>("profile");
  if (!searches.data || !apps.data || !profile.data) return null; // nothing until it is known, so nothing jumps

  const newJobs = searches.data.reduce((sum, s) => sum + s.new_count, 0);
  const attention = apps.data.data.filter((a) => a.nudge || (a.job && a.job.changes.length > 0)).length;
  const saved = apps.data.data.length;
  const hasCv = profile.data.skills.length > 0;

  const items: Item[] = [];
  if (newJobs > 0) {
    items.push({
      href: "/workspace/searches",
      figure: String(newJobs),
      label: `new job${newJobs === 1 ? "" : "s"} for your saved searches`,
      hot: true,
    });
  }
  if (attention > 0) {
    items.push({
      href: "/workspace/tracker",
      figure: String(attention),
      label: `saved job${attention === 1 ? "" : "s"} need${attention === 1 ? "s" : ""} your attention`,
      hot: true,
    });
  }
  items.push(
    hasCv
      ? { href: "/workspace/alerts", figure: "CV", label: "See the jobs that match your skills" }
      : { href: "/workspace/alerts", figure: "+", label: "Add your CV to get matching jobs" },
  );
  if (saved === 0 && searches.data.length === 0) {
    items.push({ href: "/search", figure: "☆", label: "Save a job or a search to track it here" });
  }

  return (
    <section className="wb" aria-label="Since you last visited">
      <div className="wrap">
        <p className="wb-title">Welcome back</p>
        <ul className="wb-row">
          {items.map((item) => (
            <li key={item.label}>
              <Link href={item.href} className={`wb-item${item.hot ? " wb-hot" : ""}`}>
                <span className="wb-fig">{item.figure}</span>
                <span className="wb-lbl">{item.label}</span>
                <span aria-hidden="true">→</span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
