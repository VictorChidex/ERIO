import { defineConfig, devices } from "@playwright/test";

// Browser tests run against a running stack (`docker compose up`), so they
// exercise the real website and API together. Point them elsewhere with
// E2E_BASE_URL and E2E_API_URL.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", testMatch: /.*\.e2e\.ts/, use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile",
      testMatch: /.*\.e2e\.ts/,
      use: { ...devices["Pixel 7"], viewport: { width: 360, height: 740 } },
    },
    { name: "unit", testMatch: /.*\.unit\.ts/ },
  ],
});
