// frontend/tests/e2e/dashboard-heroes.spec.ts
import { test, expect } from "@playwright/test";

test.describe("dashboard hero gallery", () => {
  test("renders all five hero tiles and the tank panel", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Now — Dashboard")).toBeVisible();
    await expect(page.getByText("Trends", { exact: false })).toBeVisible();
    await expect(page.getByText("Forecast", { exact: false })).toBeVisible();
    await expect(page.getByText("Costs", { exact: false })).toBeVisible();
    await expect(page.getByText("Records", { exact: false })).toBeVisible();
    await expect(page.getByText("MQTT", { exact: false })).toBeVisible();
  });

  for (const [label, path] of [
    ["Trends", "/trends"],
    ["Forecast", "/forecast"],
    ["Costs", "/costs"],
    ["Records", "/records"],
    ["MQTT", "/mqtt"],
  ] as const) {
    test(`clicking ${label} tile navigates to ${path}`, async ({ page }) => {
      await page.goto("/");
      await page
        .locator(`[role="link"]`, { hasText: label })
        .first()
        .click();
      await expect(page).toHaveURL(new RegExp(`${path}$`));
    });
  }
});
