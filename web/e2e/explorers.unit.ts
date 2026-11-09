import { expect, test } from "@playwright/test";

import { sparkBars } from "../app/pulse/charts";
import { atomFeed } from "../lib/feed";
import { ROLE_LABELS } from "../lib/format";
import { GUIDES } from "../lib/guides";
import { jobsBehind } from "../lib/pay";
import { allPathSlugs, relatedPaths, resolvePath, STARTER_NOTES, TITLE_CATEGORY } from "../lib/paths";
import { JOB_TITLES, STATIC_PAGE_PATHS, titleBySlug } from "../lib/seo";
import { fixedSitemapUrls } from "../lib/seo-data";

test("every role category and every curated title has a page, a note and a category", () => {
  for (const key of Object.keys(ROLE_LABELS)) {
    expect(resolvePath(key)?.kind).toBe("category");
    expect(STARTER_NOTES[key]?.length).toBeGreaterThan(80);
  }
  for (const title of JOB_TITLES) {
    const page = resolvePath(title.slug);
    expect(page?.kind).toBe("title");
    expect((TITLE_CATEGORY[title.slug] ?? "") in ROLE_LABELS).toBe(true);
    expect(relatedPaths(page!).length).toBeGreaterThan(0);
  }
  expect(resolvePath("astronaut")).toBeNull();
  expect(new Set(allPathSlugs()).size).toBe(allPathSlugs().length);
});

test("related roles point at pages that exist and never at the page itself", () => {
  for (const slug of allPathSlugs()) {
    const page = resolvePath(slug)!;
    for (const related of relatedPaths(page)) {
      expect(resolvePath(related.slug), `${slug} -> ${related.slug}`).not.toBeNull();
      expect(related.slug).not.toBe(slug);
    }
  }
});

test("there are six guides and each link in them leads to a real page", () => {
  expect(GUIDES).toHaveLength(6);
  const fixed = new Set(["/", "/search", "/companies", "/pulse", "/coverage", "/api", "/new", "/paths", "/guides", "/salary"]);
  for (const guide of GUIDES) {
    expect(guide.sections.length).toBeGreaterThanOrEqual(3);
    expect(guide.links.length).toBeGreaterThan(0);
    for (const link of guide.links) {
      const path = link.href.split("?")[0]!;
      const ok =
        fixed.has(path) ||
        (path.startsWith("/jobs/role/") && titleBySlug(path.slice(11)) !== undefined) ||
        (path.startsWith("/paths/") && resolvePath(path.slice(7)) !== null) ||
        (path.startsWith("/guides/") && GUIDES.some((g) => g.slug === path.slice(8)));
      expect(ok, `${guide.slug}: ${link.href}`).toBe(true);
    }
  }
});

test("the pages shard lists the explorers, the guides and the role pages", () => {
  const locs = fixedSitemapUrls().map((u) => u.loc);
  for (const path of STATIC_PAGE_PATHS) expect(locs.some((l) => l.endsWith(path))).toBe(true);
  expect(locs.some((l) => l.endsWith("/paths"))).toBe(true);
  expect(locs.some((l) => l.endsWith("/guides"))).toBe(true);
  expect(locs.filter((l) => l.includes("/guides/"))).toHaveLength(6);
  expect(locs.filter((l) => l.includes("/paths/"))).toHaveLength(allPathSlugs().length);
  expect(new Set(locs).size).toBe(locs.length);
});

test("the link behind a pay figure keeps its role and country", () => {
  expect(jobsBehind({ role: "healthcare", country: "NG" })).toBe("/search?role=healthcare&country=NG&ww=0&salary=1&sort=salary");
  expect(jobsBehind({ role: null, country: null })).toBe("/search?salary=1&sort=salary");
});

test("sparkline bars scale to the busiest day, and a quiet month is flat", () => {
  expect(sparkBars([0, 2, 4])).toEqual([0, 0.5, 1]);
  expect(sparkBars([0, 0])).toEqual([0, 0]);
});

test("an Atom feed lists jobs with escaped text and absolute links", () => {
  const job = {
    canonical_id: "j_1",
    title: "Nurse <night> & day",
    company: { name: "Acme", domain: null, logo_url: null },
    location_text: "Lagos, Nigeria",
    city: "Lagos",
    country_code: "NG",
    remote_scope: null,
    remote_status: "onsite" as const,
    posted_at: "2026-11-09T08:00:00Z",
    indexed_at: "2026-11-09T09:00:00Z",
    salary_min: 90_000,
    salary_max: 90_000,
    salary_currency: "USD",
    salary_period: "year" as const,
  };
  const xml = atomFeed({ title: "ERIO: Jobs", selfPath: "/feed.xml?q=nurse", jobs: [job], countryNames: {} });
  expect(xml).toContain('<feed xmlns="http://www.w3.org/2005/Atom">');
  expect(xml).toContain("<title>Nurse &lt;night&gt; &amp; day at Acme</title>");
  expect(xml).toMatch(/<link rel="alternate" type="text\/html" href="http[^"]*\/jobs\/j_1"\/>/);
  expect(xml).toContain("<updated>2026-11-09T08:00:00.000Z</updated>");
  expect(xml).toContain("Lagos, Nigeria · On-site · $90k");
  const empty = atomFeed({ title: "t", selfPath: "/feed.xml", jobs: [], countryNames: {}, now: new Date("2026-11-09T00:00:00Z") });
  expect(empty).toContain("<updated>2026-11-09T00:00:00.000Z</updated>");
  expect(empty).not.toContain("<entry>");
});
