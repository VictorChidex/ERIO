import { expect, test } from "@playwright/test";

import { freshness } from "../lib/format";
import { describeEvent, usableHistory } from "../lib/history";
import { companyHref, countryHref } from "../lib/seo";
import { companyUrl, PAGES_PER_SHARD, shardPages, shardsFor } from "../lib/seo-companies";
import { countWord, toolList } from "../lib/tools";

const pay = { salary_min: 90_000, salary_max: 90_000, salary_currency: "USD", salary_period: "year" as const };

test("an employer links to its page when the slug is known, else to a search", () => {
  expect(companyHref("Acme Co", "acme-co")).toBe("/company/acme-co");
  expect(companyHref("Acme & Co", null)).toBe("/search?q=Acme%20%26%20Co");
  expect(companyHref("Acme")).toBe("/search?q=Acme");
});

test("a country links to its landing page, never to the retired /countries path", () => {
  const slugs = new Map([["NG", "nigeria"]]);
  expect(countryHref("NG", slugs)).toBe("/jobs/in/nigeria");
  expect(countryHref("ZZ", slugs)).toBe("/search?country=ZZ");
});

test("company sitemap shards hold at most 50,000 companies", () => {
  expect(shardsFor(0)).toBe(0);
  expect(shardsFor(50_000)).toBe(1);
  expect(shardsFor(50_001)).toBe(2);
  expect(PAGES_PER_SHARD).toBe(500);
  expect(shardPages(1, 250)).toEqual([1, 2, 3]);
  expect(shardPages(2, 50_001)).toEqual([501]);
  expect(shardPages(3, 50_001)).toEqual([]);
  expect(companyUrl("a b").loc).toMatch(/\/company\/a%20b$/);
});

test("history reads as plain sentences", () => {
  expect(
    describeEvent({ at: "2026-11-01T00:00:00Z", kind: "changed", changes: { salary_min: [80_000, 90_000], salary_max: [80_000, 90_000] } }, pay),
  ).toEqual(["Pay changed from $80k to $90k"]);
  expect(describeEvent({ at: "x", kind: "changed", changes: { salary_min: [null, 90_000], salary_max: [null, 90_000] } }, pay)).toEqual([
    "Pay added: $90k",
  ]);
  expect(describeEvent({ at: "x", kind: "changed", changes: { title: ["Dev", "Senior Dev"], city: ["Lagos", "Abuja"] } }, pay)).toEqual([
    "Location changed from Lagos to Abuja",
    "Title changed from Dev to Senior Dev",
  ]);
  expect(describeEvent({ at: "x", kind: "closed" }, pay)[0]).toMatch(/^Closed/);
  expect(describeEvent({ at: "x", kind: "reopened" }, pay)[0]).toMatch(/^Reopened/);
  expect(describeEvent({ at: "x", kind: "changed", changes: null }, pay)).toEqual(["Details changed"]);
});

test("missing or malformed history is ignored", () => {
  expect(usableHistory(undefined)).toEqual([]);
  expect(usableHistory("nope")).toEqual([]);
  expect(usableHistory([{ at: "2026-11-01", kind: "closed" }, { kind: "closed" }, { at: "x", kind: "exploded" }])).toHaveLength(1);
});

test("freshness: new today and checked ago", () => {
  const now = new Date("2026-11-09T12:00:00Z");
  expect(freshness({ posted_at: "2026-11-09T02:00:00Z", last_verified_at: "2026-11-09T09:00:00Z" }, now)).toEqual({
    isNew: true,
    checked: "Checked 3h ago",
  });
  expect(freshness({ posted_at: "2026-11-05T02:00:00Z", last_verified_at: null }, now)).toEqual({ isNew: false, checked: null });
  expect(freshness({ posted_at: null, last_verified_at: null }, now).isNew).toBe(false);
});

test("the tool list comes from the published definitions", () => {
  const defs = [
    { type: "function", function: { name: "search_jobs", description: "Find jobs" } },
    { type: "function", function: { name: "get_job" } },
    { nonsense: true },
  ];
  expect(toolList(defs).map((t) => t.name)).toEqual(["search_jobs", "get_job"]);
  expect(toolList(null)).toEqual([]);
  expect(countWord(10)).toBe("ten");
  expect(countWord(30)).toBe("30");
});
