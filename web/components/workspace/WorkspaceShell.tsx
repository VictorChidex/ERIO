"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useWorkspaceData } from "@/components/workspace/Gate";
import styles from "@/components/workspace/workspace.module.css";
import { ACCENTS, type Profile } from "@/lib/profile";
import { useAdoptLink } from "@/lib/workspace";

const TABS = [
  { href: "/workspace", label: "Overview" },
  { href: "/workspace/tracker", label: "Tracker" },
  { href: "/workspace/searches", label: "Saved searches" },
  { href: "/workspace/alerts", label: "Profile & alerts" },
  { href: "/workspace/cv", label: "CV match" },
  { href: "/workspace/settings", label: "Settings" },
  { href: "/workspace/privacy", label: "Privacy" },
];

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const path = usePathname() ?? "";
  useAdoptLink();
  const { data } = useWorkspaceData<Profile>("profile");
  const accent = data ? ACCENTS[data.prefs.accent]?.color : null;
  const style = accent ? ({ "--acc": accent } as React.CSSProperties) : undefined;
  return (
    <div style={style} data-density={data?.prefs.density ?? "comfortable"}>
      <div className="page-header">
        <div className="wrap">
          <div className="eyebrow">No account · email only if you ask for alerts · nothing sold</div>
          <h1 className="page-title">Your workspace</h1>
          <nav className={styles.tabs} aria-label="Workspace">
            {TABS.map((tab) => {
              const on = tab.href === "/workspace" ? path === tab.href : path.startsWith(tab.href);
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  className={`${styles.tab} ${on ? styles.tabOn : ""}`}
                  aria-current={on ? "page" : undefined}
                >
                  {tab.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
      <div className={styles.page}>
        <div className="wrap">{children}</div>
      </div>
    </div>
  );
}
