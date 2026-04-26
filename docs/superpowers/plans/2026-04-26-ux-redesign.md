# UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the busy nine-card dashboard with a control-tower layout (tank hero + five page-hero tiles), introduce a shared hero widget per page, and split Settings into a two-pane layout — implementing the spec at `docs/superpowers/specs/2026-04-26-ux-redesign-design.md`.

**Architecture:** All changes are presentation-layer in `frontend/`. Five new Svelte components implement the page heroes — each takes a `size: "tile" | "full"` prop and renders the same chart inside two different envelopes. The dashboard composes them in a gallery; each page renders the `"full"` size at the top of its detail content. Settings is rebuilt as two coordinated panels (group nav + form) sharing a search store. Tank hero rewrites the inline dashboard code into a dedicated `TankHeroPanel` component. No backend changes.

**Tech Stack:** SvelteKit 5 (runes), TypeScript, Tailwind, ECharts (via existing `LineChart`/`BarChart`/`ForecastFan` components), Vitest (unit), Playwright (e2e).

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `frontend/src/lib/components/TankHeroPanel.svelte` | Wraps `TankSilhouette` + bars/% headline + days-to-empty + cost-to-fill + status row. The Dashboard's "now" panel. |
| `frontend/src/lib/components/HeroShell.svelte` | Visual envelope shared by all five page heroes — handles the page accent, label/range header, headline number, click-to-navigate, and `size` switch. |
| `frontend/src/lib/components/HeroTrends.svelte` | Area-line of level over 30d with refill markers. |
| `frontend/src/lib/components/HeroForecast.svelte` | Fan envelope (median + p25/p75) projecting empty date. |
| `frontend/src/lib/components/HeroCosts.svelte` | 12-month column bars (£/month, current month accented). |
| `frontend/src/lib/components/HeroRecords.svelte` | Event timeline — dots on a horizontal line, colour-coded by event type. |
| `frontend/src/lib/components/HeroMqtt.svelte` | Pulse histogram of messages-per-minute over the last 60 min. |
| `frontend/src/lib/components/SettingsNav.svelte` | Left pane — search + group list with active state. |
| `frontend/src/lib/components/SettingsForm.svelte` | Right pane — single group's form, plus the change-password form when "Account" is selected. |
| `frontend/src/lib/stores/settingsUi.ts` | Svelte store for selected group + search query. |
| `frontend/src/lib/heroes/timeline.ts` | Pure helper to bucket reading/refill/anomaly events for `HeroRecords`. |
| `frontend/src/lib/heroes/timeline.test.ts` | Vitest tests for the bucketing helper. |
| `frontend/src/lib/heroes/mqttPulse.ts` | Pure helper to bucket MQTT message timestamps into per-minute counts for `HeroMqtt`. |
| `frontend/src/lib/heroes/mqttPulse.test.ts` | Vitest tests for the pulse bucketing helper. |
| `frontend/tests/e2e/dashboard-heroes.spec.ts` | Playwright test asserting clicking each tile navigates to its page. |

### Modified files

| Path | Reason |
|---|---|
| `frontend/src/routes/+page.svelte` | Rewrite — drop nine StatCards + status pills + RunPanel + the inline tank panel; render `TankHeroPanel` + five hero tiles. |
| `frontend/src/routes/trends/+page.svelte` | Insert `<HeroTrends size="full" />` as the first panel. |
| `frontend/src/routes/forecast/+page.svelte` | Insert `<HeroForecast size="full" />` as the first panel. |
| `frontend/src/routes/costs/+page.svelte` | Insert `<HeroCosts size="full" />` as the first panel. |
| `frontend/src/routes/records/+page.svelte` | Insert `<HeroRecords size="full" />` as the first panel. |
| `frontend/src/routes/mqtt/+page.svelte` | Insert `<HeroMqtt size="full" />` as the first panel. |
| `frontend/src/routes/settings/+page.svelte` | Rewrite as two-pane shell consuming `SettingsNav` + `SettingsForm`. |
| `frontend/src/lib/components/RunPanel.svelte` | No code change, but consumed from a new location (Settings page accordion). |
| `docs/adr/0004-frontend-design-language.md` | Amend: violet/amber as legal page accents; add five new hero components to inventory. |

---

## Phase 1 — Foundation

### Task 1: Add page accent tokens to Tailwind

**Files:**
- Modify: `frontend/tailwind.config.js` (or wherever brand colours are configured)

- [ ] **Step 1: Locate current brand tokens**

Run: `grep -n "brand-blue\|brand-amber\|brand-emerald" frontend/tailwind.config.js frontend/tailwind.config.ts 2>/dev/null`

Read the matched file. Confirm the existing palette includes `brand-blue`, `brand-amber`, `brand-red`, `brand-emerald`, `brand-teal`, `brand-violet` (per ADR-0004). If any are missing, add them with the hex values from ADR-0004:
- `--blue: #3b82f6`
- `--teal: #2dd4bf`
- `--amber: #f59e0b`
- `--red: #ef4444`
- `--emerald: #10b981`
- `--violet: #a78bfa`

- [ ] **Step 2: Verify build still passes**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: build succeeds. If it fails on an unrelated issue, fix or surface to the user.

- [ ] **Step 3: Commit**

```bash
git add frontend/tailwind.config.*
git commit -m "ui: ensure all six page-accent palette tokens are exported

ADR-0004 lists blue, teal, amber, red, emerald, violet. The hero gallery
needs each as a Tailwind class so accents render with utility classes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2: Build the HeroShell envelope

**Files:**
- Create: `frontend/src/lib/components/HeroShell.svelte`

- [ ] **Step 1: Create `HeroShell.svelte`**

```svelte
<script lang="ts">
  import { goto } from "$app/navigation";

  type Accent = "teal" | "violet" | "amber" | "slate" | "emerald" | "blue";

  type Props = {
    size: "tile" | "full";
    accent: Accent;
    label: string;
    range?: string;
    headline?: string;
    sub?: string;
    href?: string;
    children?: import("svelte").Snippet;
  };

  let { size, accent, label, range, headline, sub, href, children }: Props =
    $props();

  const accentBar: Record<Accent, string> = {
    teal: "bg-brand-teal",
    violet: "bg-brand-violet",
    amber: "bg-brand-amber",
    slate: "bg-border-strong",
    emerald: "bg-brand-emerald",
    blue: "bg-brand-blue",
  };
  const accentText: Record<Accent, string> = {
    teal: "text-brand-teal",
    violet: "text-brand-violet",
    amber: "text-brand-amber",
    slate: "text-text-muted",
    emerald: "text-brand-emerald",
    blue: "text-brand-blue",
  };

  function handleClick() {
    if (href) void goto(href);
  }
</script>

<div
  class={`relative overflow-hidden rounded-lg border border-border bg-bg-panel ${size === "tile" ? "p-3" : "p-4"} ${href ? "cursor-pointer transition hover:border-border-strong" : ""}`}
  role={href ? "link" : undefined}
  tabindex={href ? 0 : undefined}
  onclick={handleClick}
  onkeydown={(e) => {
    if (href && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      handleClick();
    }
  }}
>
  <div class={`absolute left-0 top-0 h-full w-[3px] ${accentBar[accent]}`}></div>
  <div class="flex items-baseline justify-between">
    <div class={`text-[10px] font-medium uppercase tracking-wide ${accentText[accent]}`}>
      {label}
    </div>
    {#if range}
      <div class="text-[10px] text-text-subtle">{range}</div>
    {/if}
  </div>
  {#if headline}
    <div class={`mt-1 font-mono ${size === "tile" ? "text-base" : "text-2xl"} font-semibold text-text`}>
      {headline}
    </div>
  {/if}
  <div class={size === "tile" ? "mt-1" : "mt-3"}>
    {@render children?.()}
  </div>
  {#if sub}
    <div class="mt-1 text-[10px] text-text-subtle">{sub}</div>
  {/if}
</div>
```

- [ ] **Step 2: Build to verify it compiles**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/HeroShell.svelte
git commit -m "ui: add HeroShell envelope for page-hero tiles

Shared visual frame for the five page heroes — page accent on the left
edge, label + range header, optional headline number, click-to-navigate.
Switches between tile (dashboard) and full (page header) sizes via prop.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — Tank hero panel

### Task 3: Extract TankHeroPanel

**Files:**
- Create: `frontend/src/lib/components/TankHeroPanel.svelte`

- [ ] **Step 1: Create the component**

```svelte
<script lang="ts">
  import TankSilhouette from "$lib/components/TankSilhouette.svelte";
  import { liveStatus } from "$lib/stores/liveStatus";
  import { settings } from "$lib/stores/settings";

  function setting(key: string): unknown {
    return $settings.items.find((i) => i.key === key)?.value;
  }

  let reading = $derived($liveStatus.status?.reading);
  let analysis = $derived($liveStatus.status?.analysis);

  let capacity = $derived(Number(setting("tank.capacity_l") ?? 1225));
  let lengthCm = $derived(Number(setting("tank.length_cm") ?? 178.5));
  let heightCm = $derived(Number(setting("tank.height_cm") ?? 137));
  let lowThreshold = $derived(
    Number(setting("alerts.low_level_threshold_pct") ?? 20),
  );

  let pct = $derived(reading?.percentage_remaining ?? 0);
  let bars = $derived(reading?.bars_remaining ?? null);
  let daysRemaining = $derived(analysis?.estimated_days_remaining ?? null);
  let costToFill = $derived(reading?.cost_to_fill ?? null);
  let currentPpl = $derived(reading?.current_ppl ?? null);

  let levelTone = $derived<"default" | "amber" | "red">(
    pct <= lowThreshold * 0.5
      ? "red"
      : pct <= lowThreshold
        ? "amber"
        : "default",
  );
  let daysTone = $derived<"default" | "amber" | "red">(
    daysRemaining == null
      ? "default"
      : daysRemaining < 14
        ? "red"
        : daysRemaining < 30
          ? "amber"
          : "default",
  );

  function fmtNum(v: number | null | undefined, digits = 0): string {
    return v == null || !Number.isFinite(v) ? "—" : v.toFixed(digits);
  }

  const toneClass: Record<string, string> = {
    default: "text-text",
    amber: "text-brand-amber",
    red: "text-brand-red",
  };
</script>

<section class="relative overflow-hidden rounded-lg border border-border bg-bg-panel p-4">
  <div class="absolute left-0 top-0 h-full w-[3px] bg-brand-blue"></div>
  <div class="text-[10px] font-medium uppercase tracking-wide text-brand-blue">
    Now — Dashboard
  </div>

  <div class="mt-3 flex items-start gap-4">
    <div class="flex-shrink-0">
      <TankSilhouette
        percentage={pct}
        litres={reading?.litres_remaining ?? null}
        capacity={capacity}
        bars={bars}
        {lengthCm}
        {heightCm}
      />
    </div>

    <div class="flex flex-1 flex-col justify-between gap-3 self-stretch">
      <div>
        <div class="text-[10px] uppercase tracking-wide text-text-label">Bars · Remaining</div>
        <div class="mt-0.5 flex items-baseline gap-2 font-mono">
          <span class="text-2xl font-semibold text-text">{bars ?? "—"}<span class="text-sm text-text-muted">/10</span></span>
          <span class="text-text-subtle">·</span>
          <span class={`text-2xl font-semibold ${toneClass[levelTone]}`}>{fmtNum(pct, 0)}<span class="text-sm text-text-muted">%</span></span>
        </div>
        <div class="text-[11px] text-text-subtle">{fmtNum(reading?.litres_remaining, 0)} L / {Math.round(capacity)}</div>
      </div>

      <div>
        <div class="text-[10px] uppercase tracking-wide text-text-label">Days to empty</div>
        <div class="mt-0.5 font-mono">
          <span class={`text-xl font-semibold ${toneClass[daysTone]}`}>{fmtNum(daysRemaining, 0)}</span>
          {#if analysis?.estimated_empty_date}
            <span class="ml-2 text-[11px] text-text-subtle">~ {analysis.estimated_empty_date}</span>
          {/if}
        </div>
      </div>

      <div>
        <div class="text-[10px] uppercase tracking-wide text-text-label">Cost to fill</div>
        <div class="mt-0.5 font-mono">
          <span class="text-xl font-semibold text-text">£{fmtNum(costToFill as number | null | undefined, 0)}</span>
          {#if currentPpl != null}
            <span class="ml-2 text-[11px] text-text-subtle">@ {fmtNum(currentPpl, 2)} p/L</span>
          {/if}
        </div>
      </div>
    </div>
  </div>

  <div class="mt-3 flex items-center justify-between border-t border-border pt-2">
    <div class="flex flex-wrap gap-2">
      {#if reading?.refill_detected === "y"}
        <span class="rounded border border-brand-emerald/40 bg-emerald-950/40 px-2 py-1 text-[11px] text-brand-emerald">Refill detected</span>
      {/if}
      {#if reading?.leak_detected === "y"}
        <span class="rounded border border-brand-red/40 bg-red-950/40 px-2 py-1 text-[11px] text-brand-red">Leak detected</span>
      {/if}
      {#if levelTone === "red"}
        <span class="rounded border border-brand-red/40 bg-red-950/40 px-2 py-1 text-[11px] text-brand-red">Critical level — order now</span>
      {:else if levelTone === "amber"}
        <span class="rounded border border-brand-amber/40 bg-amber-950/40 px-2 py-1 text-[11px] text-brand-amber">Below {lowThreshold}% — plan a refill</span>
      {/if}
    </div>
    <div class="font-mono text-[11px] text-text-subtle">
      last reading {reading?.date ?? "—"}
    </div>
  </div>
</section>
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/TankHeroPanel.svelte
git commit -m "ui: add TankHeroPanel — tank silhouette + co-equal bars/% headline

Pulls the dashboard's tank panel out as a dedicated component. Promotes
bars and % to a co-equal headline pair (matches how the physical Watchman
gauge is read). Days-to-empty and cost-to-fill stay as secondary headlines
with generous spacing so the panel does not feel crowded.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — Page hero widgets

### Task 4: Build HeroTrends (area-line)

**Files:**
- Create: `frontend/src/lib/components/HeroTrends.svelte`

- [ ] **Step 1: Create the component**

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import * as echarts from "echarts";
  import HeroShell from "$lib/components/HeroShell.svelte";
  import { KEROTRACK_DARK_THEME } from "$lib/charts/theme";
  import { api } from "$lib/api";
  import type { Reading } from "$lib/types/api";

  type Props = { size: "tile" | "full" };
  let { size }: Props = $props();

  let chartEl = $state<HTMLDivElement | null>(null);
  let chart: echarts.ECharts | null = null;
  let readings = $state<Reading[]>([]);
  let consumedL = $derived(() => {
    if (readings.length < 2) return null;
    const first = readings[0]?.litres_remaining;
    const last = readings[readings.length - 1]?.litres_remaining;
    if (first == null || last == null) return null;
    return Math.round(first - last);
  });
  let refills = $derived(() =>
    readings.filter((r) => r.refill_detected === "y").length,
  );
  let avgLDay = $derived(() => {
    const c = consumedL();
    if (c == null || c <= 0) return null;
    return c / 30;
  });

  function isoDaysAgo(days: number): string {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - days);
    return d.toISOString().slice(0, 10);
  }

  onMount(async () => {
    try {
      const resp = await api.readings({
        since: `${isoDaysAgo(30)} 00:00:00`,
        order: "asc",
        limit: 2000,
      });
      readings = resp.items ?? [];
    } catch {
      readings = [];
    }
  });

  $effect(() => {
    if (!chartEl || readings.length === 0) return;
    chart ??= echarts.init(chartEl, KEROTRACK_DARK_THEME, { renderer: "svg" });
    const points = readings.map((r) => [r.date, r.litres_remaining]);
    const refillPoints = readings
      .filter((r) => r.refill_detected === "y")
      .map((r) => [r.date, r.litres_remaining]);
    chart.setOption({
      grid: { left: 0, right: 0, top: 4, bottom: 0 },
      xAxis: { type: "time", show: false },
      yAxis: { type: "value", show: false, scale: true },
      series: [
        {
          type: "line",
          showSymbol: false,
          smooth: true,
          lineStyle: { color: "#2dd4bf", width: 1.5 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(45,212,191,0.35)" },
                { offset: 1, color: "rgba(45,212,191,0)" },
              ],
            },
          },
          data: points,
        },
        {
          type: "scatter",
          symbolSize: 8,
          itemStyle: { color: "#10b981" },
          data: refillPoints,
        },
      ],
    });
  });
</script>

<HeroShell
  {size}
  accent="teal"
  label="Trends"
  range="30d"
  headline={consumedL() != null ? `${consumedL()! >= 0 ? "−" : "+"}${Math.abs(consumedL()!)} L` : "—"}
  sub={`${refills()} refill${refills() === 1 ? "" : "s"} · ${avgLDay() != null ? avgLDay()!.toFixed(1) : "—"} L/d avg`}
  href="/trends"
>
  <div bind:this={chartEl} class={size === "tile" ? "h-[34px] w-full" : "h-[100px] w-full"}></div>
</HeroShell>
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/HeroTrends.svelte
git commit -m "ui: add HeroTrends — area-line of level over 30d with refill markers

First of the five page heroes. Reuses ECharts via the registered
kerotrack-dark theme and the existing /api/readings endpoint. Renders
small in tile size (sparkline only) and large in full size (with hover
tooltip via ECharts defaults).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 5: Build HeroForecast (fan envelope)

**Files:**
- Create: `frontend/src/lib/components/HeroForecast.svelte`

- [ ] **Step 1: Create the component**

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import * as echarts from "echarts";
  import HeroShell from "$lib/components/HeroShell.svelte";
  import { KEROTRACK_DARK_THEME } from "$lib/charts/theme";
  import { liveStatus } from "$lib/stores/liveStatus";

  type Props = { size: "tile" | "full" };
  let { size }: Props = $props();

  let chartEl = $state<HTMLDivElement | null>(null);
  let chart: echarts.ECharts | null = null;

  let analysis = $derived($liveStatus.status?.analysis);
  let emptyDate = $derived(analysis?.estimated_empty_date ?? null);
  let daysRemaining = $derived(analysis?.estimated_days_remaining ?? null);
  let avgLDay = $derived(analysis?.avg_daily_consumption_l ?? null);
  let pct = $derived($liveStatus.status?.reading?.percentage_remaining ?? 0);

  function buildSeries() {
    if (daysRemaining == null || avgLDay == null) return null;
    const today = Date.now();
    const day = 24 * 3600 * 1000;
    const horizon = Math.min(Math.max(daysRemaining + 30, 30), 180);
    const median: [number, number][] = [];
    const p25: [number, number][] = [];
    const p75: [number, number][] = [];
    const p5: [number, number][] = [];
    const p95: [number, number][] = [];
    for (let d = 0; d <= horizon; d++) {
      const t = today + d * day;
      const consumed = avgLDay * d;
      const noise25 = avgLDay * d * 0.1;
      const noise5 = avgLDay * d * 0.25;
      const start = pct;
      const ratio = avgLDay > 0 ? consumed / (avgLDay * daysRemaining) : 0;
      const med = Math.max(0, start - ratio * start);
      median.push([t, med]);
      p25.push([t, Math.max(0, med - noise25)]);
      p75.push([t, med + noise25]);
      p5.push([t, Math.max(0, med - noise5)]);
      p95.push([t, med + noise5]);
    }
    return { median, p25, p75, p5, p95 };
  }

  $effect(() => {
    if (!chartEl) return;
    const series = buildSeries();
    if (!series) return;
    chart ??= echarts.init(chartEl, KEROTRACK_DARK_THEME, { renderer: "svg" });
    chart.setOption({
      grid: { left: 0, right: 0, top: 4, bottom: 0 },
      xAxis: { type: "time", show: false },
      yAxis: { type: "value", show: false, min: 0, max: 100 },
      series: [
        {
          type: "line",
          data: series.p95,
          showSymbol: false,
          lineStyle: { width: 0 },
          stack: "outer",
          areaStyle: { color: "rgba(167,139,250,0.08)" },
        },
        {
          type: "line",
          data: series.p75,
          showSymbol: false,
          lineStyle: { width: 0 },
          areaStyle: { color: "rgba(167,139,250,0.18)", origin: "start" },
        },
        {
          type: "line",
          data: series.median,
          showSymbol: false,
          lineStyle: { color: "#a78bfa", width: 1.5, type: "dashed" },
        },
        {
          type: "line",
          data: series.p25,
          showSymbol: false,
          lineStyle: { width: 0 },
          areaStyle: { color: "rgba(167,139,250,0.18)" },
        },
        {
          type: "line",
          data: series.p5,
          showSymbol: false,
          lineStyle: { width: 0 },
          areaStyle: { color: "rgba(167,139,250,0.08)" },
        },
      ],
    });
  });

  function fmtDate(s: string | null): string {
    if (!s) return "—";
    return s.length >= 10 ? s.slice(0, 10) : s;
  }
</script>

<HeroShell
  {size}
  accent="violet"
  label="Forecast"
  range={daysRemaining != null ? `${Math.round(daysRemaining)}d` : ""}
  headline={`~ ${fmtDate(emptyDate)}`}
  sub={daysRemaining != null ? `order in ${Math.max(0, Math.round(daysRemaining) - 14)}d window` : ""}
  href="/forecast"
>
  <div bind:this={chartEl} class={size === "tile" ? "h-[34px] w-full" : "h-[100px] w-full"}></div>
</HeroShell>
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/HeroForecast.svelte
git commit -m "ui: add HeroForecast — fan envelope with median + p25/p75 + p5/p95

Reads /api/status's analysis block (already fetched for the dashboard) and
synthesises a fan envelope client-side from estimated_days_remaining +
avg_daily_consumption_l. If a richer /api/forecast endpoint lands later
the fan can swap to that data without touching the chrome.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 6: Build HeroCosts (column bars)

**Files:**
- Create: `frontend/src/lib/components/HeroCosts.svelte`

- [ ] **Step 1: Create the component**

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import * as echarts from "echarts";
  import HeroShell from "$lib/components/HeroShell.svelte";
  import { KEROTRACK_DARK_THEME } from "$lib/charts/theme";
  import { api } from "$lib/api";

  type Props = { size: "tile" | "full" };
  let { size }: Props = $props();

  type Period = { period: string; cost?: number; total_cost?: number };

  let chartEl = $state<HTMLDivElement | null>(null);
  let chart: echarts.ECharts | null = null;
  let periods = $state<Period[]>([]);

  let last12 = $derived(periods.slice(-12));
  let thisMonth = $derived(last12[last12.length - 1] ?? null);
  let prevMonth = $derived(last12[last12.length - 2] ?? null);
  let thisCost = $derived<number | null>(
    thisMonth ? Number(thisMonth.cost ?? thisMonth.total_cost ?? null) : null,
  );
  let prevCost = $derived<number | null>(
    prevMonth ? Number(prevMonth.cost ?? prevMonth.total_cost ?? null) : null,
  );
  let delta = $derived(
    thisCost != null && prevCost != null ? thisCost - prevCost : null,
  );

  onMount(async () => {
    try {
      const resp = await api.costPeriods();
      periods = (resp.items ?? []) as unknown as Period[];
    } catch {
      periods = [];
    }
  });

  $effect(() => {
    if (!chartEl || last12.length === 0) return;
    chart ??= echarts.init(chartEl, KEROTRACK_DARK_THEME, { renderer: "svg" });
    const data = last12.map((p, i) => ({
      value: Number(p.cost ?? p.total_cost ?? 0),
      itemStyle: {
        color: i === last12.length - 1 ? "#f59e0b" : "#3b82f6",
      },
    }));
    chart.setOption({
      grid: { left: 0, right: 0, top: 4, bottom: 0 },
      xAxis: {
        type: "category",
        show: false,
        data: last12.map((p) => p.period),
      },
      yAxis: { type: "value", show: false },
      series: [
        {
          type: "bar",
          data,
          barCategoryGap: "30%",
        },
      ],
    });
  });

  function fmtMoney(v: number | null): string {
    if (v == null || !Number.isFinite(v)) return "—";
    return `£${Math.round(v)}`;
  }
  function fmtDelta(v: number | null): string {
    if (v == null || !Number.isFinite(v)) return "";
    const arrow = v >= 0 ? "▲" : "▼";
    const colour = v >= 0 ? "amber" : "emerald";
    return `${arrow} £${Math.abs(Math.round(v))}|${colour}`;
  }

  let deltaText = $derived(fmtDelta(delta));
  let deltaLabel = $derived(deltaText.split("|")[0] ?? "");
</script>

<HeroShell
  {size}
  accent="amber"
  label="Costs"
  range="12mo"
  headline={`${fmtMoney(thisCost)} ${deltaLabel}`}
  sub={prevMonth ? `vs ${fmtMoney(prevCost)} last month` : ""}
  href="/costs"
>
  <div bind:this={chartEl} class={size === "tile" ? "h-[34px] w-full" : "h-[100px] w-full"}></div>
</HeroShell>
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/HeroCosts.svelte
git commit -m "ui: add HeroCosts — 12-month column bars with current month accent

Pulls /api/costs/periods and trims to the last 12 entries. Current month
renders amber, prior months blue — a single eye-catch confirms whether
this month is unusual.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 7: Add the timeline bucketing helper (TDD)

**Files:**
- Create: `frontend/src/lib/heroes/timeline.ts`
- Create: `frontend/src/lib/heroes/timeline.test.ts`

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/lib/heroes/timeline.test.ts
import { describe, it, expect } from "vitest";
import { buildTimelineEvents, type TimelineEvent } from "./timeline";

describe("buildTimelineEvents", () => {
  it("returns an empty array for no readings", () => {
    expect(buildTimelineEvents([], 30)).toEqual([]);
  });

  it("classifies a refill reading as a refill event", () => {
    const events = buildTimelineEvents(
      [{ date: "2026-04-01 10:00:00", refill_detected: "y" } as any],
      30,
    );
    expect(events).toHaveLength(1);
    expect(events[0].kind).toBe("refill");
  });

  it("classifies an anomaly reading as an anomaly event", () => {
    const events = buildTimelineEvents(
      [{ date: "2026-04-01 10:00:00", anomaly_detected: "y" } as any],
      30,
    );
    expect(events[0].kind).toBe("anomaly");
  });

  it("classifies a normal reading as a normal event", () => {
    const events = buildTimelineEvents(
      [{ date: "2026-04-01 10:00:00" } as any],
      30,
    );
    expect(events[0].kind).toBe("normal");
  });

  it("filters out readings older than the window", () => {
    const today = new Date();
    const old = new Date(today.getTime() - 60 * 24 * 3600 * 1000)
      .toISOString()
      .slice(0, 10);
    const recent = new Date(today.getTime() - 5 * 24 * 3600 * 1000)
      .toISOString()
      .slice(0, 10);
    const events = buildTimelineEvents(
      [
        { date: `${old} 10:00:00` } as any,
        { date: `${recent} 10:00:00` } as any,
      ],
      30,
    );
    expect(events).toHaveLength(1);
  });

  it("computes a 0..1 normalised position within the window", () => {
    const today = new Date();
    const recent = new Date(today.getTime() - 0)
      .toISOString()
      .slice(0, 10);
    const oldest = new Date(today.getTime() - 30 * 24 * 3600 * 1000)
      .toISOString()
      .slice(0, 10);
    const events = buildTimelineEvents(
      [
        { date: `${oldest} 10:00:00` } as any,
        { date: `${recent} 10:00:00` } as any,
      ],
      30,
    );
    expect(events[0].position).toBeGreaterThanOrEqual(0);
    expect(events[0].position).toBeLessThanOrEqual(1);
    expect(events[1].position).toBeCloseTo(1, 1);
  });
});
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `cd frontend && npx vitest run src/lib/heroes/timeline.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the helper**

```typescript
// frontend/src/lib/heroes/timeline.ts
import type { Reading } from "$lib/types/api";

export type TimelineEvent = {
  kind: "refill" | "anomaly" | "normal";
  position: number; // 0..1 within the window
  date: string;
};

export function buildTimelineEvents(
  readings: Reading[],
  windowDays: number,
): TimelineEvent[] {
  const now = Date.now();
  const windowMs = windowDays * 24 * 3600 * 1000;
  const start = now - windowMs;
  const out: TimelineEvent[] = [];
  for (const r of readings) {
    const ts = Date.parse(r.date.replace(" ", "T") + "Z");
    if (!Number.isFinite(ts) || ts < start || ts > now) continue;
    const kind: TimelineEvent["kind"] =
      r.refill_detected === "y"
        ? "refill"
        : (r as { anomaly_detected?: string }).anomaly_detected === "y"
          ? "anomaly"
          : "normal";
    const position = Math.max(0, Math.min(1, (ts - start) / windowMs));
    out.push({ kind, position, date: r.date });
  }
  return out;
}
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `cd frontend && npx vitest run src/lib/heroes/timeline.test.ts`
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/heroes/timeline.ts frontend/src/lib/heroes/timeline.test.ts
git commit -m "ui: add timeline event bucketing helper for HeroRecords

Pure function, fully unit-tested. Classifies each reading as refill /
anomaly / normal and emits a 0..1 position within the chosen window so
the UI is purely a coordinate plot.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 8: Build HeroRecords (event timeline)

**Files:**
- Create: `frontend/src/lib/components/HeroRecords.svelte`

- [ ] **Step 1: Create the component**

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import HeroShell from "$lib/components/HeroShell.svelte";
  import { api } from "$lib/api";
  import type { Reading } from "$lib/types/api";
  import { buildTimelineEvents } from "$lib/heroes/timeline";

  type Props = { size: "tile" | "full" };
  let { size }: Props = $props();

  let readings = $state<Reading[]>([]);

  function isoDaysAgo(days: number): string {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - days);
    return d.toISOString().slice(0, 10);
  }

  onMount(async () => {
    try {
      const resp = await api.readings({
        since: `${isoDaysAgo(30)} 00:00:00`,
        order: "asc",
        limit: 2000,
      });
      readings = resp.items ?? [];
    } catch {
      readings = [];
    }
  });

  let events = $derived(buildTimelineEvents(readings, 30));
  let refillCount = $derived(events.filter((e) => e.kind === "refill").length);
  let totalReadings = $derived(events.length);

  const dotSize: Record<"tile" | "full", { normal: number; special: number }> = {
    tile: { normal: 4, special: 8 },
    full: { normal: 6, special: 12 },
  };
  const colours: Record<string, string> = {
    refill: "#10b981",
    anomaly: "#f59e0b",
    normal: "#3b82f6",
  };
</script>

<HeroShell
  {size}
  accent="slate"
  label="Records"
  range="30d"
  headline={`${totalReadings} readings · ${refillCount} refill${refillCount === 1 ? "" : "s"}`}
  sub="green = refill · amber = anomaly · blue = normal"
  href="/records"
>
  <div class={`relative w-full ${size === "tile" ? "h-[34px]" : "h-[100px]"}`}>
    <div class="absolute left-0 right-0 top-1/2 h-px bg-border-strong"></div>
    {#each events as e}
      {@const sz = e.kind === "normal" ? dotSize[size].normal : dotSize[size].special}
      <div
        class="absolute rounded-full"
        style={`left: calc(${e.position * 100}% - ${sz / 2}px); top: calc(50% - ${sz / 2}px); width: ${sz}px; height: ${sz}px; background:${colours[e.kind]};`}
      ></div>
    {/each}
  </div>
</HeroShell>
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/HeroRecords.svelte
git commit -m "ui: add HeroRecords — event timeline of readings, refills, anomalies

Renders a horizontal lane with one dot per reading event over the last 30
days. Uses the buildTimelineEvents helper so the visual layer is pure
coordinate plotting — easy to scan and easy to test.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 9: Add the MQTT pulse helper (TDD)

**Files:**
- Create: `frontend/src/lib/heroes/mqttPulse.ts`
- Create: `frontend/src/lib/heroes/mqttPulse.test.ts`

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/lib/heroes/mqttPulse.test.ts
import { describe, it, expect } from "vitest";
import { bucketMessagesPerMinute } from "./mqttPulse";

describe("bucketMessagesPerMinute", () => {
  it("returns 60 zero-buckets for an empty list", () => {
    const buckets = bucketMessagesPerMinute([], Date.now());
    expect(buckets).toHaveLength(60);
    expect(buckets.every((b) => b === 0)).toBe(true);
  });

  it("counts one message in the correct bucket", () => {
    const now = Date.UTC(2026, 3, 26, 12, 0, 0);
    const buckets = bucketMessagesPerMinute(
      [now - 30 * 1000], // 30s ago — last bucket
      now,
    );
    expect(buckets[59]).toBe(1);
    expect(buckets.slice(0, 59).every((b) => b === 0)).toBe(true);
  });

  it("ignores messages older than 60 minutes", () => {
    const now = Date.UTC(2026, 3, 26, 12, 0, 0);
    const buckets = bucketMessagesPerMinute([now - 61 * 60 * 1000], now);
    expect(buckets.every((b) => b === 0)).toBe(true);
  });

  it("ignores messages from the future", () => {
    const now = Date.UTC(2026, 3, 26, 12, 0, 0);
    const buckets = bucketMessagesPerMinute([now + 60 * 1000], now);
    expect(buckets.every((b) => b === 0)).toBe(true);
  });

  it("counts multiple messages in the same minute together", () => {
    const now = Date.UTC(2026, 3, 26, 12, 0, 0);
    const buckets = bucketMessagesPerMinute(
      [now - 10 * 1000, now - 20 * 1000, now - 40 * 1000],
      now,
    );
    expect(buckets[59]).toBe(3);
  });
});
```

- [ ] **Step 2: Run the tests**

Run: `cd frontend && npx vitest run src/lib/heroes/mqttPulse.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the helper**

```typescript
// frontend/src/lib/heroes/mqttPulse.ts
const WINDOW_MIN = 60;

export function bucketMessagesPerMinute(
  timestampsMs: number[],
  nowMs: number,
): number[] {
  const buckets = new Array<number>(WINDOW_MIN).fill(0);
  const start = nowMs - WINDOW_MIN * 60 * 1000;
  for (const t of timestampsMs) {
    if (t < start || t > nowMs) continue;
    const idx = Math.min(
      WINDOW_MIN - 1,
      Math.floor((t - start) / (60 * 1000)),
    );
    buckets[idx] += 1;
  }
  return buckets;
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run src/lib/heroes/mqttPulse.test.ts`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/heroes/mqttPulse.ts frontend/src/lib/heroes/mqttPulse.test.ts
git commit -m "ui: add MQTT message pulse bucketing helper

Buckets a list of message timestamps into 60 per-minute counts for the
last hour. Pure function, fully unit-tested.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 10: Build HeroMqtt (pulse histogram)

**Files:**
- Create: `frontend/src/lib/components/HeroMqtt.svelte`

- [ ] **Step 1: Create the component**

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import HeroShell from "$lib/components/HeroShell.svelte";
  import { api } from "$lib/api";
  import { liveStatus } from "$lib/stores/liveStatus";
  import { bucketMessagesPerMinute } from "$lib/heroes/mqttPulse";

  type Props = { size: "tile" | "full" };
  let { size }: Props = $props();

  let timestamps = $state<number[]>([]);
  let now = $state(Date.now());

  let connected = $derived($liveStatus.health?.mqtt_connected ?? false);
  let topics = $derived<number>(
    Number(($liveStatus.health as { mqtt_topics?: number } | null)?.mqtt_topics ?? 0),
  );
  let lastMs = $derived(timestamps.length ? timestamps[timestamps.length - 1] : null);
  let agoText = $derived(() => {
    if (lastMs == null) return "—";
    const sec = Math.max(0, Math.round((now - lastMs) / 1000));
    if (sec < 60) return `${sec}s`;
    if (sec < 3600) return `${Math.round(sec / 60)} min`;
    return `${Math.round(sec / 3600)} h`;
  });

  let buckets = $derived(bucketMessagesPerMinute(timestamps, now));
  let maxBucket = $derived(buckets.reduce((m, v) => (v > m ? v : m), 0));

  onMount(() => {
    void load();
    const t = setInterval(() => {
      now = Date.now();
      void load();
    }, 30000);
    return () => clearInterval(t);
  });

  async function load() {
    try {
      const resp = await api.mqttFeed(500);
      timestamps = (resp.items ?? []).map((m) => m.ts * 1000);
    } catch {
      // keep last good state
    }
  }
</script>

<HeroShell
  {size}
  accent="emerald"
  label="MQTT"
  range="60m"
  headline={`${connected ? "● Connected" : "○ Off"} · ${agoText()} ago`}
  sub={`${timestamps.length} msgs · ${topics} topic${topics === 1 ? "" : "s"}`}
  href="/mqtt"
>
  <div class={`flex w-full items-end gap-px ${size === "tile" ? "h-[34px]" : "h-[100px]"}`}>
    {#each buckets as count}
      {@const h = maxBucket > 0 ? Math.max(2, (count / maxBucket) * 100) : 2}
      <div class="flex-1 bg-brand-emerald" style={`height: ${h}%; opacity: ${count > 0 ? 0.4 + (count / Math.max(1, maxBucket)) * 0.5 : 0.15};`}></div>
    {/each}
  </div>
</HeroShell>
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/HeroMqtt.svelte
git commit -m "ui: add HeroMqtt — message-pulse histogram for the last 60 minutes

Renders 60 vertical bars (one per minute) showing message density.
Polls /api/mqtt-feed every 30s and recomputes via the bucketing helper.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — Dashboard rewrite

### Task 11: Rewrite the dashboard route

**Files:**
- Modify: `frontend/src/routes/+page.svelte`

- [ ] **Step 1: Replace the file's contents**

```svelte
<script lang="ts">
  import { onMount } from "svelte";

  import HeroCosts from "$lib/components/HeroCosts.svelte";
  import HeroForecast from "$lib/components/HeroForecast.svelte";
  import HeroMqtt from "$lib/components/HeroMqtt.svelte";
  import HeroRecords from "$lib/components/HeroRecords.svelte";
  import HeroTrends from "$lib/components/HeroTrends.svelte";
  import TankHeroPanel from "$lib/components/TankHeroPanel.svelte";
  import { liveStatus } from "$lib/stores/liveStatus";
  import { settings } from "$lib/stores/settings";

  onMount(() => {
    void liveStatus.refresh();
    void settings.refresh();
  });

  let reading = $derived($liveStatus.status?.reading);
</script>

<div class="grid grid-cols-12 gap-4">
  <section class="col-span-12 lg:col-span-5">
    <TankHeroPanel />
  </section>

  <section class="col-span-12 lg:col-span-7">
    <div class="grid grid-cols-2 gap-3">
      <HeroTrends size="tile" />
      <HeroForecast size="tile" />
      <HeroCosts size="tile" />
      <HeroRecords size="tile" />
      <div class="col-span-2"><HeroMqtt size="tile" /></div>
    </div>
  </section>

  {#if reading == null}
    <p class="col-span-12 text-sm text-text-muted">
      No readings yet — point <code class="font-mono">mqtt.broker</code> at your real
      broker via Settings, or run the Phase 6 migrator to import a v1 snapshot.
    </p>
  {/if}
</div>
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/+page.svelte
git commit -m "ui: rewrite dashboard as control-tower — tank hero + 5 hero tiles

Drops the nine flat StatCards, the status pills row, and the inline
RunPanel. The dashboard now composes TankHeroPanel + the five page heroes
in a 5/7 split grid. Each hero tile deep-links to its page.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 12: Add an e2e test for hero navigation

**Files:**
- Create: `frontend/tests/e2e/dashboard-heroes.spec.ts`

- [ ] **Step 1: Write the test**

```typescript
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
```

- [ ] **Step 2: Run the e2e suite to confirm the test runs**

Run: `cd frontend && npx playwright test dashboard-heroes.spec.ts --reporter=line 2>&1 | tail -20`
Expected: tests pass when the dev server is reachable. If the test runner cannot reach the dev server in CI, surface that to the user — the goal here is to record the test, not to break a working pipeline.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/dashboard-heroes.spec.ts
git commit -m "test: cover dashboard hero gallery rendering and click-through

Asserts all five heroes plus the tank panel render, and that clicking
each tile navigates to the corresponding page.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 5 — Page header integration

### Task 13: Insert HeroTrends into Trends page

**Files:**
- Modify: `frontend/src/routes/trends/+page.svelte`

- [ ] **Step 1: Add the import and render the hero**

Locate the existing top of the markup section (after the `<script>` block ends, before the first existing chart panel). Add the import to the script:

```typescript
import HeroTrends from "$lib/components/HeroTrends.svelte";
```

Insert at the very top of the markup (above the existing range selector):

```svelte
<HeroTrends size="full" />
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/trends/+page.svelte
git commit -m "ui: anchor Trends page with HeroTrends at full size

Same component as the dashboard tile, rendered larger. Existing detail
charts (line, daily bars, scatter, calendar heatmap) remain below.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 14: Insert HeroForecast into Forecast page

**Files:**
- Modify: `frontend/src/routes/forecast/+page.svelte`

- [ ] **Step 1: Add the import and render the hero**

Add to script imports:

```typescript
import HeroForecast from "$lib/components/HeroForecast.svelte";
```

Insert at the very top of the markup:

```svelte
<HeroForecast size="full" />
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/forecast/+page.svelte
git commit -m "ui: anchor Forecast page with HeroForecast at full size

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 15: Insert HeroCosts into Costs page

**Files:**
- Modify: `frontend/src/routes/costs/+page.svelte`

- [ ] **Step 1: Add the import and render the hero**

Add to script imports:

```typescript
import HeroCosts from "$lib/components/HeroCosts.svelte";
```

Insert at the very top of the markup:

```svelte
<HeroCosts size="full" />
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/costs/+page.svelte
git commit -m "ui: anchor Costs page with HeroCosts at full size

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 16: Insert HeroRecords into Records page

**Files:**
- Modify: `frontend/src/routes/records/+page.svelte`

- [ ] **Step 1: Add the import and render the hero**

Add to script imports:

```typescript
import HeroRecords from "$lib/components/HeroRecords.svelte";
```

Insert at the very top of the markup:

```svelte
<HeroRecords size="full" />
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/records/+page.svelte
git commit -m "ui: anchor Records page with HeroRecords at full size

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 17: Insert HeroMqtt into MQTT page

**Files:**
- Modify: `frontend/src/routes/mqtt/+page.svelte`

- [ ] **Step 1: Add the import and render the hero**

Add to script imports:

```typescript
import HeroMqtt from "$lib/components/HeroMqtt.svelte";
```

Insert at the very top of the markup:

```svelte
<HeroMqtt size="full" />
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/mqtt/+page.svelte
git commit -m "ui: anchor MQTT page with HeroMqtt at full size

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 6 — Settings two-pane

### Task 18: Add the settings UI store

**Files:**
- Create: `frontend/src/lib/stores/settingsUi.ts`

- [ ] **Step 1: Create the store**

```typescript
// frontend/src/lib/stores/settingsUi.ts
import { writable } from "svelte/store";

const KEY = "kerotrack.settings.activeGroup";

function loadInitial(): string {
  if (typeof localStorage === "undefined") return "tank";
  return localStorage.getItem(KEY) ?? "tank";
}

export const activeGroup = writable<string>(loadInitial());

activeGroup.subscribe((v) => {
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(KEY, v);
  }
});

export const search = writable<string>("");
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/stores/settingsUi.ts
git commit -m "ui: add settings UI store — active group + search query

Persists the last-selected group across reloads via localStorage.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 19: Add SettingsNav

**Files:**
- Create: `frontend/src/lib/components/SettingsNav.svelte`

- [ ] **Step 1: Create the component**

```svelte
<script lang="ts">
  import { settings } from "$lib/stores/settings";
  import { activeGroup, search } from "$lib/stores/settingsUi";

  let groupEntries = $derived(() => {
    const entries = Object.entries($settings.groups).map(
      ([g, items]) => ({ group: g, count: items.length }),
    );
    entries.push({ group: "account", count: 1 });
    return entries;
  });

  function setActive(g: string) {
    activeGroup.set(g);
  }
</script>

<aside class="flex w-44 flex-col gap-2 rounded-lg border border-border bg-bg-panel p-2">
  <input
    type="text"
    class="w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-xs text-text placeholder:text-text-subtle"
    placeholder="Search settings…"
    bind:value={$search}
  />
  <nav class="flex flex-col gap-px">
    {#each groupEntries() as { group, count } (group)}
      <button
        type="button"
        class={`flex items-center justify-between rounded px-2 py-1 text-left text-xs ${$activeGroup === group ? "border-l-2 border-brand-blue bg-bg-elev pl-1.5 text-text" : "text-text-muted hover:text-text"}`}
        onclick={() => setActive(group)}
      >
        <span class="capitalize">{group}</span>
        <span class="rounded bg-border px-1.5 py-0.5 font-mono text-[10px] text-text-subtle">{count}</span>
      </button>
    {/each}
  </nav>
</aside>
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/SettingsNav.svelte
git commit -m "ui: add SettingsNav — group sidebar with search and counts

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 20: Add SettingsForm

**Files:**
- Create: `frontend/src/lib/components/SettingsForm.svelte`

- [ ] **Step 1: Create the component**

```svelte
<script lang="ts">
  import { stringToArray, getSchedule } from "cron-converter";
  import { api, ApiError } from "$lib/api";
  import { settings } from "$lib/stores/settings";
  import { activeGroup, search } from "$lib/stores/settingsUi";
  import type { SettingDef, SettingItem } from "$lib/types/api";

  type Props = {
    pending: Record<string, unknown>;
    onChange: (key: string, value: unknown) => void;
  };
  let { pending, onChange }: Props = $props();

  let oldPassword = $state("");
  let newPassword = $state("");
  let confirmPassword = $state("");
  let pwSubmitting = $state(false);
  let pwError = $state<string | null>(null);
  let pwOk = $state(false);

  function defFor(key: string): SettingDef | undefined {
    return $settings.schema.find((d) => d.key === key);
  }
  function display(item: SettingItem): unknown {
    if (item.is_secret) return "";
    return pending[item.key] !== undefined ? pending[item.key] : item.value;
  }
  function nextCronFires(expr: string, count = 3): string[] {
    if (!expr || typeof expr !== "string") return [];
    try {
      const arr = stringToArray(expr.trim());
      const sched = getSchedule(arr, new Date());
      const fmt = new Intl.DateTimeFormat(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
      return Array.from({ length: count }, () => fmt.format(sched.next().toDate()));
    } catch {
      return [];
    }
  }

  let visibleItems = $derived(() => {
    const q = $search.trim().toLowerCase();
    if (q) {
      return $settings.items.filter(
        (i) =>
          i.key.toLowerCase().includes(q) ||
          (i.label ?? "").toLowerCase().includes(q),
      );
    }
    if ($activeGroup === "account") return [];
    return $settings.groups[$activeGroup] ?? [];
  });

  async function changePassword(e: Event) {
    e.preventDefault();
    pwError = null;
    pwOk = false;
    if (newPassword !== confirmPassword) {
      pwError = "Passwords don't match";
      return;
    }
    if (newPassword.length < 12) {
      pwError = "New password must be at least 12 characters";
      return;
    }
    pwSubmitting = true;
    try {
      await api.changePassword(oldPassword, newPassword);
      pwOk = true;
      oldPassword = "";
      newPassword = "";
      confirmPassword = "";
    } catch (err) {
      pwError = err instanceof ApiError ? err.message : (err as Error).message;
    } finally {
      pwSubmitting = false;
    }
  }
</script>

<section class="flex-1 rounded-lg border border-border bg-bg-panel">
  <header class="flex items-center justify-between border-b border-border px-4 py-2">
    <div>
      <div class="text-xs font-medium uppercase tracking-wide text-text-muted">
        {$search.trim() ? "Search results" : $activeGroup}
      </div>
      <div class="text-[11px] text-text-subtle">
        {$search.trim()
          ? `${visibleItems().length} match${visibleItems().length === 1 ? "" : "es"}`
          : `${visibleItems().length} setting${visibleItems().length === 1 ? "" : "s"}`}
      </div>
    </div>
  </header>

  {#if $activeGroup === "account" && !$search.trim()}
    <form class="grid max-w-md gap-3 px-4 py-4" onsubmit={changePassword}>
      <input
        type="password"
        placeholder="Current password"
        class="rounded border border-border bg-bg-elev px-2 py-1.5 text-sm"
        bind:value={oldPassword}
        autocomplete="current-password"
        required
      />
      <input
        type="password"
        placeholder="New password (min 12 chars)"
        class="rounded border border-border bg-bg-elev px-2 py-1.5 text-sm"
        bind:value={newPassword}
        autocomplete="new-password"
        required
      />
      <input
        type="password"
        placeholder="Confirm new password"
        class="rounded border border-border bg-bg-elev px-2 py-1.5 text-sm"
        bind:value={confirmPassword}
        autocomplete="new-password"
        required
      />
      {#if pwError}<p class="text-xs text-brand-red">{pwError}</p>{/if}
      {#if pwOk}<p class="text-xs text-brand-emerald">Password updated.</p>{/if}
      <button
        type="submit"
        class="w-fit rounded bg-brand-blue px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        disabled={pwSubmitting}
      >
        {pwSubmitting ? "Updating…" : "Update password"}
      </button>
    </form>
  {:else}
    <div class="divide-y divide-border">
      {#each visibleItems() as item (item.key)}
        {@const def = defFor(item.key)}
        <div class="group grid grid-cols-12 items-center gap-3 px-4 py-2.5">
          <label class="col-span-5 text-sm text-text">
            <span title={def?.description ?? ""}>
              {def?.label ?? item.label}
              {#if def?.description}
                <span class="ml-1 cursor-help text-text-subtle" aria-label="info">ⓘ</span>
              {/if}
            </span>
            <div class="font-mono text-[10px] text-text-subtle opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">{item.key}</div>
          </label>
          <div class="col-span-7">
            {#if item.value_type === "bool"}
              <input
                type="checkbox"
                checked={display(item) as boolean}
                onchange={(e) => onChange(item.key, (e.currentTarget as HTMLInputElement).checked)}
              />
            {:else if item.value_type === "json"}
              <textarea
                class="w-full rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                rows="2"
                oninput={(e) => {
                  try {
                    onChange(item.key, JSON.parse((e.currentTarget as HTMLTextAreaElement).value));
                  } catch {
                    /* keep typing */
                  }
                }}
                >{JSON.stringify(display(item) ?? [], null, 2)}</textarea
              >
            {:else if item.value_type === "secret"}
              <input
                type="password"
                placeholder="(unchanged — type to set new value)"
                class="w-full rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                oninput={(e) => onChange(item.key, (e.currentTarget as HTMLInputElement).value)}
              />
            {:else if item.value_type === "cron"}
              {@const cronValue = (display(item) ?? "") as string}
              {@const fires = nextCronFires(cronValue)}
              <input
                type="text"
                class="w-full rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                value={cronValue}
                oninput={(e) => onChange(item.key, (e.currentTarget as HTMLInputElement).value)}
              />
              {#if fires.length > 0}
                <div class="mt-1 space-y-0.5 text-xs text-text-subtle">
                  <div class="font-medium text-text-muted">Next 3 fires:</div>
                  {#each fires as fire}
                    <div>· {fire}</div>
                  {/each}
                </div>
              {:else if cronValue.trim()}
                <div class="mt-1 text-xs text-brand-red">Invalid cron expression</div>
              {/if}
            {:else if item.value_type === "int" || item.value_type === "float"}
              <input
                type="number"
                step={def?.step ?? (item.value_type === "int" ? 1 : "any")}
                class="w-32 rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                value={display(item) as number}
                oninput={(e) => {
                  const raw = (e.currentTarget as HTMLInputElement).value;
                  onChange(item.key, item.value_type === "int" ? parseInt(raw, 10) : parseFloat(raw));
                }}
              />
            {:else}
              <input
                type="text"
                class="w-full rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                value={display(item) as string}
                oninput={(e) => onChange(item.key, (e.currentTarget as HTMLInputElement).value)}
              />
            {/if}
          </div>
        </div>
      {/each}
      {#if visibleItems().length === 0}
        <p class="px-4 py-6 text-sm text-text-subtle">No matches.</p>
      {/if}
    </div>
  {/if}
</section>
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/SettingsForm.svelte
git commit -m "ui: add SettingsForm — single group's fields with cleaned-up rows

Hides dotted-key until row is hovered/focused, moves description to a (ⓘ)
tooltip, sizes inputs to value type, and includes the change-password form
under the synthetic Account group.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 21: Rewrite the Settings route as two-pane

**Files:**
- Modify: `frontend/src/routes/settings/+page.svelte`

- [ ] **Step 1: Replace the file's contents**

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import SettingsForm from "$lib/components/SettingsForm.svelte";
  import SettingsNav from "$lib/components/SettingsNav.svelte";
  import { ApiError } from "$lib/api";
  import { settings } from "$lib/stores/settings";

  let pending = $state<Record<string, unknown>>({});
  let saving = $state(false);
  let saveError = $state<string | null>(null);
  let saveOk = $state(false);

  onMount(() => {
    void settings.refresh();
  });

  function setPending(key: string, value: unknown) {
    pending = { ...pending, [key]: value };
    saveOk = false;
  }

  async function save() {
    if (!Object.keys(pending).length) return;
    saving = true;
    saveError = null;
    try {
      await settings.save(pending);
      pending = {};
      saveOk = true;
    } catch (err) {
      saveError = err instanceof ApiError ? err.message : (err as Error).message;
    } finally {
      saving = false;
    }
  }
</script>

<div class="space-y-4">
  <header class="flex items-center justify-between">
    <h1 class="text-lg font-semibold">Settings</h1>
    <div class="flex items-center gap-3">
      {#if saveError}<span class="text-xs text-brand-red">{saveError}</span>{/if}
      {#if saveOk}<span class="text-xs text-brand-emerald">Saved</span>{/if}
      <button
        class="rounded bg-brand-blue px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        onclick={save}
        disabled={saving || !Object.keys(pending).length}
      >
        {saving ? "Saving…" : `Save${Object.keys(pending).length ? ` (${Object.keys(pending).length})` : ""}`}
      </button>
    </div>
  </header>

  {#if $settings.error}
    <p class="text-xs text-brand-red">{$settings.error}</p>
  {/if}

  <div class="flex items-start gap-4">
    <SettingsNav />
    <SettingsForm {pending} onChange={setPending} />
  </div>
</div>
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/settings/+page.svelte
git commit -m "ui: rewrite Settings as two-pane (group nav + single-group form)

Replaces the tall accordion with a sidebar of groups + a focused form on
the right. Search filters across groups. Save button stays in the page
header with the dirty-field count.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 7 — Cleanup + ADR

### Task 22: Add a Maintenance group on Settings to host RunPanel

**Files:**
- Modify: `frontend/src/routes/settings/+page.svelte`
- Modify: `frontend/src/lib/components/SettingsForm.svelte`

- [ ] **Step 1: Wire RunPanel into the SettingsForm fall-through**

In `SettingsForm.svelte`, add a `RunPanel` import and a branch that renders it when `$activeGroup === "maintenance"`:

In the `<script>` block, add:

```typescript
import RunPanel from "$lib/components/RunPanel.svelte";
```

Add a new top-level `{:else if}` to the existing `{#if $activeGroup === "account" && !$search.trim()}` chain (in the markup) — replace the chain so it reads:

```svelte
{#if $activeGroup === "account" && !$search.trim()}
  <!-- existing account form -->
{:else if $activeGroup === "maintenance" && !$search.trim()}
  <div class="px-4 py-4">
    <RunPanel />
  </div>
{:else}
  <!-- existing field grid -->
{/if}
```

In `SettingsNav.svelte`, extend the appended entries:

```typescript
let groupEntries = $derived(() => {
  const entries = Object.entries($settings.groups).map(
    ([g, items]) => ({ group: g, count: items.length }),
  );
  entries.push({ group: "maintenance", count: 1 });
  entries.push({ group: "account", count: 1 });
  return entries;
});
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/SettingsNav.svelte frontend/src/lib/components/SettingsForm.svelte
git commit -m "ui: relocate RunPanel under Settings → Maintenance

Manual scrape and reload controls aren't part of 'now' on the dashboard.
Settings is the right home; the existing RunPanel component is reused as-is.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 23: Update ADR-0004 to widen page accents and list new components

**Files:**
- Modify: `docs/adr/0004-frontend-design-language.md`

- [ ] **Step 1: Append a "Page accents (amendment 2026-04-26)" subsection under "Semantic colour rule"**

Insert after the existing semantic colour bullets:

```markdown
### Page accents (amendment 2026-04-26)

The page-hero gallery on the Dashboard and the per-page hero envelope use a 3 px left-edge accent in the page's signature colour. These uses extend — but do not contradict — the semantic colour rule:

- **Trends → teal** — Trends owns the temperature lane, which already justifies teal on the page.
- **Forecast → violet** — violet was already designated for secondary chart series; the forecast fan envelope is exactly that.
- **Costs → amber** — already used as the table accent for emphasis in cost tables.
- **Records → slate (`--border-strong`)** — neutral; Records has no semantic colour.
- **MQTT → emerald** — connection health uses emerald already.
- **Dashboard tank panel → blue** — primary lane.

Decorative use of these colours on charts or stat cards remains forbidden; only the 3 px accent strip and the page-label text use the page colour.
```

Replace the **Component inventory** table to add the new entries:

```markdown
| `TankHeroPanel.svelte` | Dashboard |
| `HeroShell.svelte` | All five page heroes |
| `HeroTrends.svelte` | Dashboard, Trends |
| `HeroForecast.svelte` | Dashboard, Forecast |
| `HeroCosts.svelte` | Dashboard, Costs |
| `HeroRecords.svelte` | Dashboard, Records |
| `HeroMqtt.svelte` | Dashboard, MQTT |
| `SettingsNav.svelte` + `SettingsForm.svelte` | Settings |
```

(Remove the old `StatusPills.svelte`, `Sparkline.svelte`, and `SettingField.svelte` entries if they no longer correspond to actual files; otherwise leave them.)

- [ ] **Step 2: Sanity-read the ADR**

Run: `grep -n "Page accents" docs/adr/0004-frontend-design-language.md`
Expected: matches the new heading.

- [ ] **Step 3: Commit**

```bash
git add docs/adr/0004-frontend-design-language.md
git commit -m "docs: amend ADR-0004 with page-accent rules and new component inventory

Records the deliberate widening of violet/amber as page accents (within
their existing semantic meaning) and adds the new hero components.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 24: Run the full frontend test suite + manual verify

**Files:**
- (no edits)

- [ ] **Step 1: Run unit tests**

Run: `cd frontend && npm test`
Expected: PASS.

- [ ] **Step 2: Run the e2e suite**

Run: `cd frontend && npx playwright test --reporter=line 2>&1 | tail -20`
Expected: PASS. If a flake is unrelated to this change, surface it to the user.

- [ ] **Step 3: Run the backend security invariants (sanity)**

Run: `cd backend && python -m pytest tests/api/test_security_invariants.py -q 2>&1 | tail -10`
Expected: PASS — this change is presentation-only and should not affect security tests.

- [ ] **Step 4: Manual UI verification on dev server**

Start the dev server and verify by browser:

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173` and confirm:
- Dashboard renders the tank panel + 5 hero tiles on a 1080p viewport without scrolling.
- Bars + % render at equal weight in the tank panel headline.
- Each hero tile is clickable and navigates to its page.
- Each page shows the same hero at full size as its first panel.
- Settings shows the group sidebar and a focused form; switching groups swaps the form; search filters across groups; saving still works; the Maintenance entry shows the RunPanel; the Account entry shows the change-password form.

If any of these fail, fix in a follow-up task before the final commit.

- [ ] **Step 5: Commit any final tweaks (or skip)**

If no tweaks were needed, skip. Otherwise:

```bash
git add -A
git commit -m "ui: post-verification tweaks for UX redesign

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**

- ✅ Dashboard "control tower" layout — Task 11.
- ✅ Tank hero with bars+% co-equal headline + days-to-empty + cost-to-fill — Task 3.
- ✅ Five distinct hero shapes (area-line, fan, column bars, event timeline, pulse histogram) — Tasks 4, 5, 6, 8, 10.
- ✅ Hero envelope shared across tile and full sizes — Task 2.
- ✅ Per-page hero header injection — Tasks 13–17.
- ✅ Settings two-pane with group nav + single-group form + search — Tasks 18, 19, 20, 21.
- ✅ Per-row settings cleanups (key on hover/focus, description on tooltip, input width by type) — Task 20.
- ✅ Change-password as Account group entry — Task 20.
- ✅ RunPanel relocated to Settings → Maintenance — Task 22.
- ✅ ADR amendment for violet/amber page accents and new component inventory — Task 23.
- ✅ Verification (unit + e2e + manual) — Task 24.

**Placeholder scan:** No "TBD" / "implement later" / "similar to Task N" / vague error handling. Each step has its full code or its full command.

**Type consistency:** `HeroShell` props (`size`, `accent`, `label`, `range`, `headline`, `sub`, `href`) are used the same way in Tasks 4, 5, 6, 8, 10. `buildTimelineEvents`, `bucketMessagesPerMinute`, and `activeGroup`/`search` store names match across their definition and consumption tasks.

---

## Open follow-ups (out of scope for this plan)

- Swap `HeroForecast`'s synthetic envelope for a real `/api/forecast` endpoint when one lands (the chart code is contained in the component and easy to reroute).
- Add hover tooltips to the `HeroRecords` event dots showing exact date + reading details.
- Mobile/tablet layout pass — current grid stacks on narrow widths but spacing isn't tuned.
- Light-mode polish for the new components.
