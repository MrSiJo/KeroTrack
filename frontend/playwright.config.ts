import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for KeroTrack v2 smoke tests.
 *
 * Defaults to running against the deployed docker host
 * (`http://172.16.0.83:9177`) so the tests exercise what's actually
 * shipped. Override the target with `PLAYWRIGHT_BASE_URL` to point at a
 * dev server or preview deployment.
 *
 * Tests live under `tests/e2e/`. Run with `npm run test:e2e`.
 */
const baseURL =
  process.env.PLAYWRIGHT_BASE_URL ?? "http://172.16.0.83:9177";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
