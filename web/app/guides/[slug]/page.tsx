import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { GUIDES, guideBySlug } from "@/lib/guides";
import { absoluteUrl, breadcrumbJsonLd, scriptJson } from "@/lib/seo";

import styles from "../guides.module.css";

type Props = { params: Promise<{ slug: string }> };

export const dynamicParams = false;

export function generateStaticParams() {
  return GUIDES.map((guide) => ({ slug: guide.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const guide = guideBySlug((await params).slug);
  if (!guide) return { title: "Guide" };
  return {
    title: guide.title,
    description: guide.description,
    alternates: { canonical: absoluteUrl(`/guides/${guide.slug}`) },
  };
}

export default async function GuidePage({ params }: Props) {
  const guide = guideBySlug((await params).slug);
  if (!guide) notFound();
  const trail = [
    { name: "ERIO", path: "/" },
    { name: "Guides", path: "/guides" },
    { name: guide.title, path: `/guides/${guide.slug}` },
  ];
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: scriptJson(breadcrumbJsonLd(trail)) }} />
      <div className="page-header">
        <div className="wrap">
          <nav className="jd-crumbs" aria-label="Breadcrumb">
            <Link href="/">Home</Link>
            {" / "}
            <Link href="/guides">Guides</Link>
          </nav>
          <div className="sect-eye">◉ Guide</div>
          <h1 className="page-title">{guide.title}</h1>
          <p className="page-sub">{guide.description}</p>
        </div>
      </div>
      <div className="wrap">
        <article className={styles.prose}>
          {guide.sections.map((section) => (
            <section key={section.heading}>
              <h2>{section.heading}</h2>
              {section.paragraphs.map((text) => (
                <p key={text}>{text}</p>
              ))}
              {section.list && (
                <ul>
                  {section.list.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
            </section>
          ))}
        </article>
        <div className={styles.next}>
          {guide.links.map((link, index) => (
            <Link key={link.href} className={index === 0 ? "btn-acc" : "btn-ghost"} href={link.href}>
              {link.label}
            </Link>
          ))}
        </div>
      </div>
    </>
  );
}
