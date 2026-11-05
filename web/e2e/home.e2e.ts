import { expect, test } from "@playwright/test";

const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000";

const DARK_BG = "rgb(6, 10, 18)";
const LIGHT_BG = "rgb(238, 242, 248)";

test.describe("home page", () => {
  test("shows the hero and the live API status", async ({ page, request }) => {
    const health = await (await request.get(`${API_URL}/v1/health`)).json();

    await page.goto("/");

    await expect(page).toHaveTitle(/ERIO/);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Every open job, in every country.",
    );
    await expect(page.getByRole("status")).toHaveText(`API online v${health.version}`);
  });

  test("loads the bundled fonts", async ({ page }) => {
    await page.goto("/");
    const loaded = await page.evaluate(async () => {
      await document.fonts.ready;
      return [...document.fonts].filter((font) => font.status === "loaded").length;
    });
    // Display, text and mono families are all in use on the page.
    expect(loaded).toBeGreaterThanOrEqual(3);
  });

  test("never scrolls sideways", async ({ page }) => {
    await page.goto("/");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
  });
});

test.describe("theme", () => {
  test("is dark by default", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.*/);
    await expect(page.locator("body")).toHaveCSS("background-color", DARK_BG);
    await expect(page.getByRole("button", { name: "Toggle colour theme" })).toHaveText(
      "Light mode",
    );
  });

  test("toggles to light and back, and remembers the choice", async ({ page }) => {
    await page.goto("/");
    const toggle = page.getByRole("button", { name: "Toggle colour theme" });

    await toggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(page.locator("body")).toHaveCSS("background-color", LIGHT_BG);
    await expect(toggle).toHaveText("Dark mode");

    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(toggle).toHaveText("Dark mode");

    await toggle.click();
    await expect(page.locator("body")).toHaveCSS("background-color", DARK_BG);
    await page.reload();
    await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.*/);
  });

  test("applies a saved light theme before first paint", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("erio-theme", "light"));
    // Record the theme as soon as the document is parsed, before React runs.
    await page.addInitScript(() => {
      document.addEventListener("DOMContentLoaded", () => {
        (window as unknown as { themeAtParse?: string }).themeAtParse =
          document.documentElement.dataset.theme;
      });
    });

    await page.goto("/");

    const themeAtParse = await page.evaluate(
      () => (window as unknown as { themeAtParse?: string }).themeAtParse,
    );
    expect(themeAtParse).toBe("light");
  });

  test("is keyboard operable", async ({ page }) => {
    await page.goto("/");
    const toggle = page.getByRole("button", { name: "Toggle colour theme" });
    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  });
});
