import { expect, test } from "@playwright/test";

/**
 * Smoke tests against the deployed v2 stack.
 *
 * These check the bare minimum: the static frontend loads, the auth
 * guard redirects to /login (or /setup on a fresh deploy), and the API
 * health endpoint reports `db: ok`. Anything deeper than this requires
 * fixture data and credentials in CI — out of scope for v2.0.
 */

test("frontend root redirects to login or setup when not authenticated", async ({
  page,
}) => {
  await page.goto("/");
  // Auth guard kicks the user to /login (or /setup on the first boot).
  await expect(page).toHaveURL(/\/(login|setup)$/);
  await expect(page.locator("body")).toContainText(/KeroTrack|Sign in|Setup/i);
});

test("login page renders username + password inputs", async ({ page }) => {
  await page.goto("/login");
  // Setup flow may redirect to /setup if needs_setup; tolerate both.
  if (page.url().endsWith("/setup")) {
    await expect(page.locator("input").first()).toBeVisible();
    return;
  }
  await expect(page.locator('input[type="password"]').first()).toBeVisible();
});

test("api health endpoint reports db ok", async ({ request, baseURL }) => {
  const apiBase = (baseURL ?? "http://172.16.0.83:9177").replace(":9177", ":9176");
  const resp = await request.get(`${apiBase}/api/health`);
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  expect(body.status).toBe("ok");
  expect(body.db).toBe("ok");
});
