import { expect, test } from "@playwright/test";

import { ROLE_LABELS } from "../lib/format";
import {
  breadcrumbJsonLd,
  countryBySlug,
  countrySlugs,
  headline,
  inSitemap,
  isThin,
  JOB_TITLES,
  jobPageTitle,
  landingPath,
  pageDescription,
  pageTitle,
  resolveSegment,
  robotsFor,
  robotsTxt,
  sitemapIndexXml,
  SITEMAP_MIN,
  slugify,
  snippet,
  THIN_PAGE_MIN,
  urlsetXml,
} from "../lib/seo";

const countries = [
  { code: "DE", name: "Germany" },
  { code: "GB", name: "United Kingdom" },
  { code: "CI", name: "Côte d'Ivoire" },
];

test("slugs are plain lower-case words", () => {
  expect(slugify("São Paulo")).toBe("sao-paulo");
  expect(slugify("Côte d'Ivoire")).toBe("cote-d-ivoire");
  expect(slugify("Bosnia & Herzegovina")).toBe("bosnia-and-herzegovina");
});

test("a country slug maps back to its country", () => {
  const slugs = countrySlugs(countries);
  expect(slugs.get("GB")).toBe("united-kingdom");
  expect(countryBySlug(countries, "germany")?.code).toBe("DE");
  expect(countryBySlug(countries, "cote-d-ivoire")?.code).toBe("CI");
  expect(countryBySlug(countries, "atlantis")).toBeUndefined();
});

test("countries that would share a slug keep their ISO code in it", () => {
  const twins = [
    { code: "AA", name: "Same Land" },
    { code: "BB", name: "Same-Land" },
  ];
  expect([...countrySlugs(twins).values()]).toEqual(["same-land-aa", "same-land-bb"]);
  expect(countryBySlug(twins, "same-land-bb")?.code).toBe("BB");
});

test("title slugs never collide with role categories", () => {
  for (const title of JOB_TITLES) expect(title.slug in ROLE_LABELS).toBe(false);
  expect(new Set(JOB_TITLES.map((t) => t.slug)).size).toBe(JOB_TITLES.length);
});

test("the second path segment resolves to a role, a title or a city", () => {
  const cities = [{ name: "São Paulo" }, { name: "Lagos" }];
  expect(resolveSegment("healthcare", cities)).toEqual({ kind: "role", role: "healthcare" });
  expect(resolveSegment("electrician", cities)).toMatchObject({ kind: "title" });
  expect(resolveSegment("sao-paulo", cities)).toEqual({ kind: "city", city: "São Paulo" });
  expect(resolveSegment("nowhere", cities)).toBeNull();
});

test("pages with too few jobs are noindex but still followed", () => {
  expect(isThin(THIN_PAGE_MIN - 1)).toBe(true);
  expect(isThin(THIN_PAGE_MIN)).toBe(false);
  expect(robotsFor(0)).toEqual({ index: false, follow: true });
  expect(robotsFor(THIN_PAGE_MIN)).toEqual({ index: true, follow: true });
});

test("the sitemap bar is higher than the thin-page bar", () => {
  expect(SITEMAP_MIN).toBeGreaterThan(THIN_PAGE_MIN);
  expect(inSitemap(SITEMAP_MIN - 1)).toBe(false);
  expect(inSitemap(SITEMAP_MIN)).toBe(true);
});

test("titles, descriptions and paths follow the page patterns", () => {
  const slugs = countrySlugs(countries);
  const de = { code: "DE", name: "Germany" };
  const electrician = JOB_TITLES.find((t) => t.slug === "electrician")!;
  const landing = { kind: "country-title", country: de, title: electrician } as const;
  expect(headline(landing)).toBe("Electrician jobs in Germany");
  expect(pageTitle(landing, 12, 2026)).toBe("Electrician jobs in Germany — 12 open roles (2026)");
  expect(pageTitle(landing, 1, 2026)).toContain("1 open role ");
  expect(pageDescription(landing, 12)).toContain("12 open Electrician jobs in Germany");
  expect(landingPath(landing, slugs)).toBe("/jobs/in/germany/electrician");
  expect(landingPath({ kind: "role-title", title: electrician }, slugs)).toBe("/jobs/role/electrician");
  expect(landingPath({ kind: "country-role", country: de, role: "trades" }, slugs)).toBe("/jobs/in/germany/trades");
  expect(headline({ kind: "country-city", country: de, city: "Berlin" })).toBe("Jobs in Berlin, Germany");
});

test("job page titles and descriptions", () => {
  const job = { title: "Nurse", company: { name: "Charité" }, city: "Berlin", country_code: "DE" };
  expect(jobPageTitle(job, { DE: "Germany" })).toBe("Nurse at Charité in Berlin, Germany");
  expect(jobPageTitle({ ...job, city: null, country_code: null }, {})).toBe("Nurse at Charité");
  expect(snippet("  one\n\n two ", "fallback")).toBe("one two");
  expect(snippet(null, "fallback")).toBe("fallback");
  expect(snippet("word ".repeat(100), "x").length).toBeLessThanOrEqual(160);
});

test("breadcrumbs are absolute and numbered from 1", () => {
  const ld = breadcrumbJsonLd([
    { name: "ERIO", path: "/" },
    { name: "Jobs in Germany", path: "/jobs/in/germany" },
  ]) as { itemListElement: { position: number; item: string }[] };
  expect(ld.itemListElement.map((i) => i.position)).toEqual([1, 2]);
  expect(ld.itemListElement[1]?.item).toMatch(/^https?:\/\/.+\/jobs\/in\/germany$/);
});

test("robots.txt blocks filtered search and AI training, and names the sitemap", () => {
  const txt = robotsTxt("https://erio.example");
  expect(txt).toContain("Disallow: /search");
  expect(txt).toContain("Disallow: /jobs?");
  expect(txt).toContain("Allow: /jobs?page=");
  expect(txt).toContain("Disallow: /api/");
  expect(txt).toMatch(/User-agent: GPTBot\nDisallow: \/\n/);
  expect(txt).toMatch(/User-agent: ClaudeBot\nDisallow: \/\n/);
  expect(txt).toContain("ai-train=no");
  expect(txt).toContain("Sitemap: https://erio.example/sitemap.xml");
});

test("sitemap XML escapes addresses and lists every entry", () => {
  const urlset = urlsetXml([{ loc: "https://erio.example/a?x=1&y=2" }, { loc: "https://erio.example/b" }]);
  expect(urlset).toContain("<loc>https://erio.example/a?x=1&amp;y=2</loc>");
  expect(urlset.match(/<url>/g)).toHaveLength(2);
  expect(sitemapIndexXml([{ loc: "https://erio.example/sitemaps/pages.xml" }])).toContain("<sitemap><loc>");
});
