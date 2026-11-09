import type { Metadata } from "next";
import Link from "next/link";

import styles from "@/app/pulse/insights.module.css";
import { ApiUnavailable, getPulse } from "@/lib/api";
import { formatCount, ROLE_LABELS } from "@/lib/format";
import { absoluteUrl, breadcrumbJsonLd, JOB_TITLES, scriptJson } from "@/lib/seo";
import { titleTotals } from "@/lib/seo-data";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Role explorer",
  description:
    "For each kind of work: open roles, where they are, who hires, what they advertise it pays, how fast hiring is moving, and how to get started.",
  alternates: { canonical: absoluteUrl("/paths") },
};

export default async function PathsPage() {
  const [pulse, titles] = await Promise.all([
    getPulse()
      .then((p) => p.data)
      .catch((error) => {
        if (error instanceof ApiUnavailable) return null;
        throw error;
      }),
    titleTotals().catch(() => JOB_TITLES.map((title) => ({ title, total: null as number | null }))),
  ]);
  const counts = new Map(pulse?.roles.map((r) => [r.key, r.count]));
  const trail = [
    { name: "ERIO", path: "/" },
    { name: "Role explorer", path: "/paths" },
  ];
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: scriptJson(breadcrumbJsonLd(trail)) }} />
      <div className="page-header">
        <div className="wrap">
          <div className="sect-eye">◉ Role explorer</div>
          <h1 className="page-title">Pick a kind of work.</h1>
          <p className="page-sub">
            Each page shows the open roles, where they are, who is hiring, what they advertise it pays and
            how fast hiring is moving, with a short note on getting started.
          </p>
        </div>
      </div>
      <div className="wrap">
        <section className={styles.section}>
          <h2 className={styles.h2}>Fields</h2>
          <div className={styles.list}>
            {Object.entries(ROLE_LABELS).map(([key, label]) => (
              <Link className={styles.co} key={key} href={`/paths/${key}`}>
                <span className={styles.coName}>{label}</span>
                <span className={styles.coNum}>{counts.has(key) ? `${formatCount(counts.get(key) ?? 0)} open` : ""}</span>
              </Link>
            ))}
          </div>
        </section>
        <section className={styles.section}>
          <h2 className={styles.h2}>Job titles</h2>
          <div className={styles.list}>
            {titles.map(({ title, total }) => (
              <Link className={styles.co} key={title.slug} href={`/paths/${title.slug}`}>
                <span className={styles.coName}>{title.label}</span>
                <span className={styles.coNum}>{total === null ? "" : `${formatCount(total)} open`}</span>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
