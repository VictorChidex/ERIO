// Globe behaviour (spec step 11) on the running site.

import { expect, type Page, test } from "@playwright/test";

async function readyGlobe(page: Page, selector: string) {
  const canvas = page.locator(`${selector} canvas.globe-canvas`);
  await expect(canvas).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
  return canvas;
}

/** Moves the mouse over the globe until the tooltip names a country, then returns its position. */
async function findCountry(page: Page, selector: string): Promise<{ x: number; y: number; name: string }> {
  const canvas = await readyGlobe(page, selector);
  const box = (await canvas.boundingBox())!;
  for (const fy of [0.47, 0.4, 0.55, 0.33, 0.62]) {
    for (const fx of [0.5, 0.42, 0.58, 0.34, 0.66]) {
      const x = box.x + box.width * fx, y = box.y + box.width * fy;
      await page.mouse.move(x, y);
      await page.waitForTimeout(150);
      const tip = page.locator("#gtip b");
      if (await tip.isVisible()) return { x, y, name: (await tip.textContent()) ?? "" };
    }
  }
  throw new Error("no country found under the globe");
}

test.describe("globe", () => {
  test.skip(({ isMobile }) => isMobile, "pointer tests run on desktop; the country list covers phones");

  test("loads lazily without blocking the page", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await readyGlobe(page, ".globe-wrap");
  });

  test("clicking a country on the home globe opens search filtered to it", async ({ page }) => {
    // A spinning globe can turn another country under the pointer between
    // finding a country and clicking it; reduced motion holds it still.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    const spot = await findCountry(page, ".globe-wrap");
    await page.mouse.click(spot.x, spot.y);
    await expect(page).toHaveURL(/\/search\?country=[A-Z]{2}$/);
    await expect(page.locator(".af").first()).toContainText(spot.name);
  });

  test("clicking a country on the search globe adds it to the filter", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/search");
    const spot = await findCountry(page, ".ph-globe");
    await page.mouse.click(spot.x, spot.y);
    await expect(page).toHaveURL(/country=[A-Z]{2}/);
    await expect(page.locator(".af").first()).toContainText(spot.name);
  });

  test("reduced motion turns off spin and arcs", async ({ browser }) => {
    const context = await browser.newContext({ reducedMotion: "reduce" });
    const page = await context.newPage();
    await page.goto("/");
    await expect(await readyGlobe(page, ".globe-wrap")).toHaveAttribute("data-motion", "reduced");
    await context.close();
  });

  // Frame timing depends on the machine and on what else runs at the same time,
  // so it is not a CI gate: headless browsers draw in software and measured
  // anywhere from 10 to 35 fps here. Run it on the reference laptop with
  // GLOBE_PERF=1 npx playwright test globe --workers=1 (target: 60 fps).
  test("keeps a smooth frame rate", async ({ page }) => {
    test.skip(!process.env.GLOBE_PERF, "set GLOBE_PERF=1 to measure the frame rate");
    await page.goto("/");
    await readyGlobe(page, ".globe-wrap");
    const fps = await page.evaluate(
      () =>
        new Promise<number>((resolve) => {
          let frames = 0;
          const start = performance.now();
          const tick = () => {
            frames++;
            if (performance.now() - start < 2000) requestAnimationFrame(tick);
            else resolve((frames * 1000) / (performance.now() - start));
          };
          requestAnimationFrame(tick);
        }),
    );
    const canvas = page.locator(".globe-wrap canvas.globe-canvas");
    await expect(canvas).toHaveAttribute("data-draw-ms", /\d/);
    console.log(`globe: ${fps.toFixed(1)} fps, median draw ${await canvas.getAttribute("data-draw-ms")} ms`);
    expect(fps).toBeGreaterThan(55);
  });
});
