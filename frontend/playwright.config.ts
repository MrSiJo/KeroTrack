import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for KeroTrack v2 smoke tests.
 *
 * Set `PLAYWRIGHT_BASE_URL` to the deployment under test (e.g.
 * `http://kerotrack.lan:9177`). Falls back to `http://localhost:9177` so
 * a developer running the stack locally can `npm run test:e2e` without
 * extra config. No environment-specific addresses are baked in.
 *
 * Tests live under `tests/e2e/`. Run with `npm run test:e2e`.
 */
const baseURL =
  process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:9177";

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
