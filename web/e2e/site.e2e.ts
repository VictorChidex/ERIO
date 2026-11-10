// Browser tests for the website against a running stack (spec step 10). They
// work on any data: CI loads the recorded demo jobs, a local stack has real
// crawls. Every number is checked against what the API itself reports.

import { expect, type Page, test } from "@playwright/test";

const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000";

type Country = { code: string; name: string; job_count: number; local_job_count: number };

async function api<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get(`${API_URL}${path}`);
  expect(response.ok(), `${path} answered ${response.status()}`).toBeTruthy();
  return (await response.json()) as T;
}

async function busiestCountry(page: Page): Promise<Country> {
  const { data } = await api<{ data: Country[] }>(page, "/v1/countries");
  const country = [...data].sort((a, b) => b.local_job_count - a.local_job_count)[0];
  expect(country?.local_job_count ?? 0, "the stack needs some jobs (load demo data)").toBeGreaterThan(0);
  return country as Country;
}

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBe(0);
}

test.describe("home", () => {
  test("shows live numbers from the API", async ({ page }) => {
    const stats = await api<{ total_jobs: number; countries_with_jobs: number }>(page, "/v1/stats");
    await page.goto("/");

    await expect(page).toHaveTitle(/ERIO/);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Every open job.");
    const total = new Intl.NumberFormat("en-US").format(stats.total_jobs);
    await expect(page.getByRole("status").first()).toContainText(`Live — ${total} jobs indexed`);
    await expect(page.locator(".stat").first()).toContainText(total);
    await noSidewaysScroll(page);
  });

  test("never claims sources ERIO does not read", async ({ page }) => {
    await page.goto("/");
    const text = await page.locator("main").innerText();
    expect(text).not.toMatch(/78 (sources|connectors|platforms)/i);
    expect(text).not.toMatch(/LinkedIn|Indeed/);
  });

  test("searching from the hero opens the search page", async ({ page }) => {
    const country = await busiestCountry(page);
    await page.goto("/");
    await page.locator("#si").fill("engineer");
    await page.locator("form[role=search] select").selectOption(country.code);
    await page.locator("form[role=search] .search-btn").click();
    await expect(page).toHaveURL(new RegExp(`/search\\?q=engineer&country=${country.code}$`));
  });

  test("loads the bundled fonts", async ({ page }) => {
    await page.goto("/");
    const loaded = await page.evaluate(async () => {
      await document.fonts.ready;
      return [...document.fonts].filter((font) => font.status === "loaded").length;
    });
    expect(loaded).toBeGreaterThanOrEqual(3);
  });
});

test.describe("search", () => {
  test("filters by country, with counts that match the API", async ({ page }) => {
    const country = await busiestCountry(page);
    const expected = await api<{ meta: { total: number } }>(page, `/v1/jobs?country=${country.code}`);
    await page.goto(`/search?country=${country.code}`);

    const total = new Intl.NumberFormat("en-US").format(expected.meta.total);
    await expect(page.locator(".rc")).toContainText(`${total} job`);
    await expect(page.locator(".af").first()).toContainText(country.name);
    await expect(page.locator(".jg .jcard")).toHaveCount(Math.min(25, expected.meta.total));
    await noSidewaysScroll(page);
  });

  test("ticking a filter updates the URL and the results", async ({ page }) => {
    const country = await busiestCountry(page);
    await page.goto(`/search?country=${country.code}`);
    await page.locator('input[name="type"][value="remote"]').uncheck();

    await expect(page).toHaveURL(new RegExp(`country=${country.code}&type=hybrid,onsite`));
    const expected = await api<{ meta: { total: number } }>(
      page,
      `/v1/jobs?country=${country.code}&remote_status=hybrid,onsite`,
    );
    const total = new Intl.NumberFormat("en-US").format(expected.meta.total);
    await expect(page.locator(".rc")).toContainText(`${total} job`);
  });

  test("removing a country chip clears it from the URL", async ({ page }) => {
    const country = await busiestCountry(page);
    await page.goto(`/search?country=${country.code}`);
    await page.getByRole("link", { name: `Remove ${country.name}` }).click();
    await expect(page).toHaveURL(/\/search$/);
    await expect(page.locator(".af-lbl")).toHaveText("Popular:");
  });

  test("a copied search URL shows the same results", async ({ page, browser }) => {
    const country = await busiestCountry(page);
    const url = `/search?country=${country.code}&sort=salary`;
    await page.goto(url);
    const first = await page.locator(".jct-link").allTextContents();

    const other = await browser.newPage();
    await other.goto(url);
    expect(await other.locator(".jct-link").allTextContents()).toEqual(first);
    await other.close();
  });

  test("load more appends the next page", async ({ page }) => {
    const all = await api<{ meta: { total: number } }>(page, "/v1/jobs");
    test.skip(all.meta.total <= 25, "needs more than one page of jobs");
    await page.goto("/search");
    await page.getByRole("button", { name: "Load more jobs" }).click();
    await expect(page.locator(".jcard")).toHaveCount(Math.min(50, all.meta.total));
    const links = await page.locator(".jct-link").evaluateAll((els) => els.map((e) => e.getAttribute("href")));
    expect(new Set(links).size).toBe(links.length);
  });

  test("explains an empty result and offers a way out", async ({ page }) => {
    await page.goto("/search?q=zzqxwvnotajob");
    await expect(page.getByRole("heading", { name: /No matching listings/ })).toBeVisible();
    await expect(page.getByRole("link", { name: "Reset filters" })).toBeVisible();
  });
});

test.describe("pages", () => {
  test("a job page has the full description, where it was found and breadcrumbs, but no JobPosting data", async ({
    page,
  }) => {
    await page.goto("/search");
    await page.locator(".jct-link").first().click();
    await expect(page).toHaveURL(/\/jobs\/j_/);

    // Candidates apply on the employer's page, so the page offers breadcrumbs and no JobPosting.
    const scripts = await page.locator('script[type="application/ld+json"]').allTextContents();
    const types = scripts.map((text) => JSON.parse(text)["@type"]);
    expect(types).toContain("BreadcrumbList");
    expect(types).not.toContain("JobPosting");
    await expect(page.getByRole("heading", { level: 1 })).not.toBeEmpty();
    await expect(page.getByRole("heading", { name: "Sources" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Last checked" })).toBeVisible();
    await expect(page.getByRole("link", { name: /Apply on/ })).toHaveAttribute("href", /^https:\/\//);
    await expect(page.locator(".jd-desc script")).toHaveCount(0);
  });

  test("a country landing page shows that country's jobs", async ({ page }) => {
    const country = await busiestCountry(page);
    // The first country page lives on as a permanent redirect to the landing page.
    await page.goto(`/countries/${country.code.toLowerCase()}`);
    await expect(page).toHaveURL(/\/jobs\/in\/[a-z-]+$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(`Jobs in ${country.name}`);
    await expect(page.getByRole("heading", { name: "Latest openings" })).toBeVisible();
  });

  test("an unknown job or country is a 404", async ({ page }) => {
    expect((await page.goto("/jobs/j_doesnotexist"))?.status()).toBe(404);
    expect((await page.goto("/countries/zz"))?.status()).toBe(404);
  });

  test("coverage lists every first-release source", async ({ page }) => {
    await page.goto("/coverage");
    for (const name of ["Greenhouse", "Lever", "Ashby", "SmartRecruiters", "Recruitee", "Workable"]) {
      await expect(page.locator(".pc-name", { hasText: name })).toBeVisible();
    }
  });

  test("the API page is generated from the OpenAPI spec", async ({ page }) => {
    await page.goto("/api");
    await expect(page.locator(".eph", { hasText: /^\/v1\/jobs$/ })).toBeVisible();
    await expect(page.locator(".param-row code", { hasText: /^country$/ })).toBeVisible();
    await expect(page.getByText("YOUR_ERIO_TOKEN").first()).toBeVisible();
  });
});

test.describe("theme", () => {
  test("is dark by default and remembers light", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("body")).toHaveCSS("background-color", "rgb(6, 10, 18)");
    const toggle = page.getByRole("button", { name: "Toggle colour theme" });

    await toggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(page.locator("body")).toHaveCSS("background-color", "rgb(238, 242, 248)");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

    await page.goto("/search");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await toggle.click();
    await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.*/);
  });

  test("applies a saved light theme before first paint", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("erio-theme", "light"));
    await page.addInitScript(() => {
      document.addEventListener("DOMContentLoaded", () => {
        (window as unknown as { themeAtParse?: string }).themeAtParse = document.documentElement.dataset.theme;
      });
    });
    await page.goto("/");
    expect(await page.evaluate(() => (window as unknown as { themeAtParse?: string }).themeAtParse)).toBe("light");
  });

  test("is keyboard operable", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Toggle colour theme" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  });
});
