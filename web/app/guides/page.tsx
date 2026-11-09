import type { Metadata } from "next";
import Link from "next/link";

import { GUIDES } from "@/lib/guides";
import { absoluteUrl, breadcrumbJsonLd, scriptJson } from "@/lib/seo";

import styles from "./guides.module.css";

export const metadata: Metadata = {
  title: "Guides",
  description: "Plain guides to searching on ERIO, finding remote work, following a search in a feed reader, reading a job's freshness, privacy and where the jobs come from.",
  alternates: { canonical: absoluteUrl("/guides") },
};

export default function GuidesPage() {
  const trail = [
    { name: "ERIO", path: "/" },
    { name: "Guides", path: "/guides" },
  ];
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: scriptJson(breadcrumbJsonLd(trail)) }} />
      <div className="page-header">
        <div className="wrap">
          <nav className="jd-crumbs" aria-label="Breadcrumb">
            <Link href="/">Home</Link>
          </nav>
          <div className="sect-eye">◉ Guides</div>
          <h1 className="page-title">Using ERIO well.</h1>
          <p className="page-sub">Short guides on how the site works and what it does with your searches.</p>
        </div>
      </div>
      <div className="wrap">
        <div className={styles.index}>
          {GUIDES.map((guide) => (
            <Link key={guide.slug} className={styles.card} href={`/guides/${guide.slug}`}>
              <h2>{guide.title}</h2>
              <p>{guide.description}</p>
            </Link>
          ))}
        </div>
      </div>
    </>
  );
}
