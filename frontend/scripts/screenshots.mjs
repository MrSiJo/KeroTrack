import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

const BASE_URL = process.env.KEROTRACK_URL ?? "http://localhost:9177";
const USERNAME = process.env.KEROTRACK_USER;
const PASSWORD = process.env.KEROTRACK_PASS;
const HEADED = process.env.KEROTRACK_HEADED === "1" || (!USERNAME && !PASSWORD);

const OUT_DIR = resolve(__dirname, "../../assets/screenshots");

const VIEWPORT = { width: 1440, height: 900 };
const SCALE = 2;

const PAGES = [
  { path: "/", file: "dashboard.png", settle: 1500 },
  { path: "/trends", file: "trends.png", settle: 2500 },
  { path: "/records", file: "records.png", settle: 1500 },
  { path: "/costs", file: "costs.png", settle: 2500 },
  { path: "/forecast", file: "forecast.png", settle: 2500 },
  { path: "/mqtt", file: "mqtt.png", settle: 1500 },
  { path: "/settings", file: "settings.png", settle: 1500 },
];

async function main() {
  await mkdir(OUT_DIR, { recursive: true });

  // The backend ships its session cookie with Secure=true (per
  // bootstrap.py defaults). When the deploy is reached over plain
  // HTTP — as with the raw container port at :9177 — browsers refuse
  // to store the cookie, so login returns 200 but every follow-up is
  // 401. The flag below tells Chromium to treat this specific origin
  // as a trustworthy context, restoring Secure-cookie storage over
  // HTTP. Production browsers should still hit this app via HTTPS
  // through nginx-proxy-manager — this is a screenshot-tooling
  // workaround, not a deployment recommendation.
  const browser = await chromium.launch({
    headless: !HEADED,
    args: [`--unsafely-treat-insecure-origin-as-secure=${BASE_URL}`],
  });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: SCALE,
  });
  const page = await context.newPage();

  if (HEADED) {
    console.log(
      `Headed mode — opening ${BASE_URL}/login.\n` +
        `  Sign in manually in the browser. The script resumes once\n` +
        `  the authenticated shell renders (5-minute timeout).\n`,
    );
    page.on("console", (msg) =>
      console.log(`  [browser console:${msg.type()}] ${msg.text()}`),
    );
    page.on("pageerror", (err) =>
      console.log(`  [browser pageerror] ${err.message}`),
    );
    page.on("response", (resp) => {
      const url = resp.url();
      if (url.includes("/api/auth/") || url.includes("/api/setup/")) {
        console.log(
          `  [api] ${resp.request().method()} ${url} → ${resp.status()}`,
        );
      }
    });
    await page.goto(`${BASE_URL}/login`);
    // Wait for the sidebar nav to render — only present on authed pages.
    // Catches the case where the URL briefly leaves /login during the
    // SPA navigation but the auth guard then bounces back.
    await page.waitForSelector("aside nav a[href='/trends']", {
      state: "visible",
      timeout: 5 * 60_000,
    });
    // Small extra delay to let any post-auth data fetches settle before
    // the dashboard screenshot loop begins.
    await page.waitForTimeout(1500);
    console.log("  auth detected — taking over");
  } else {
    console.log(`Logging in to ${BASE_URL} as ${USERNAME}…`);
    const loginResp = await context.request.post(
      `${BASE_URL}/api/auth/login`,
      {
        data: { username: USERNAME, password: PASSWORD },
        headers: { "Content-Type": "application/json" },
      },
    );
    if (!loginResp.ok()) {
      const body = await loginResp.text();
      throw new Error(`Login failed (${loginResp.status()}): ${body}`);
    }
    const cookies = await context.cookies();
    console.log(`  auth ok — ${cookies.length} cookies set`);
  }

  for (const { path, file, settle } of PAGES) {
    const url = `${BASE_URL}${path}`;
    process.stdout.write(`  ${path.padEnd(12)} → ${file} … `);
    // Use `domcontentloaded` not `networkidle` — the dashboard's
    // liveStatus SSE stream stays open indefinitely, so networkidle
    // never fires and the navigation times out at 30s. The settle
    // timeout below covers chart renders + post-load data fetches.
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(settle);
    const out = resolve(OUT_DIR, file);
    await page.screenshot({ path: out, fullPage: false });
    console.log("ok");
  }

  await browser.close();
  console.log(`\nDone. Screenshots in ${OUT_DIR}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
