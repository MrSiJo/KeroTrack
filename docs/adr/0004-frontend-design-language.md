# ADR-0004: Frontend design language

**Status:** Accepted
**Date:** 2026-04-25
**Plan:** [`docs/plans/2026-04-25-v2-redesign.md`](../plans/2026-04-25-v2-redesign.md) §7
**Validated against:** seven-page mockup tour reviewed and approved by the project owner

## Context

v1 was Flask + Jinja2 + server-rendered Plotly. Sparse, piecemeal, no consistent visual language, server-side chart rendering. The v2 redesign approves a SvelteKit + TypeScript SPA, but doesn't commit to *what it looks like*. Without a design language locked in, every new component would re-litigate spacing, palette, and chart vocabulary.

## Decision

The design language is locked to the following rules. They're load-bearing — components and pages get rejected at review if they break these.

### Palette

Slate/blue base, refined for sensor data:

| Role | Token | Value |
|---|---|---|
| Page background | `--bg-page` | `#0a0f1c` |
| Panel background | `--bg-panel` | `#0f172a` |
| Elevated input bg | `--bg-elev` | `#1a2438` |
| Border | `--border` | `#1e293b` |
| Border (strong) | `--border-strong` | `#334155` |
| Text | `--text` | `#e2e8f0` |
| Text muted | `--text-muted` | `#94a3b8` |
| Text subtle | `--text-subtle` | `#64748b` |
| Text label | `--text-label` | `#475569` |
| Primary | `--blue` | `#3b82f6` |
| Primary hover | `--blue-2` | `#60a5fa` |
| Primary highlight | `--blue-3` | `#93c5fd` |
| Temperature | `--teal` | `#2dd4bf` |
| Caution | `--amber` | `#f59e0b` |
| Alarm | `--red` | `#ef4444` |
| Good news | `--emerald` | `#10b981` |
| Secondary chart series | `--violet` | `#a78bfa` |

**Dark by default.** Light mode is a derivative — the dark palette is the design target. Theme toggle persists to `localStorage`.

### Semantic colour rule

Amber, red, emerald, and teal are reserved for state. Never decorative. Specifically:

- **Amber** — caution. Stale data, anomaly highlight, scrape failure within tolerance.
- **Red** — alarm. Leak detected, very low level, MQTT disconnected, hard scrape failure.
- **Emerald** — good news. Refill detected, scheduler caught up, healthy connection.
- **Teal** — temperature lane. Used on dual-axis charts and the temperature stat. Never used elsewhere.
- **Violet** — secondary chart series only (e.g. HomeFuelsDirect price line as the fallback source).

### Page accents (amendment 2026-04-26)

The page-hero gallery on the Dashboard and the per-page hero envelope use a 3 px left-edge accent in the page's signature colour. These uses extend — but do not contradict — the semantic colour rule:

- **Trends → teal** — Trends owns the temperature lane, which already justifies teal on the page.
- **Forecast → violet** — violet was already designated for secondary chart series; the forecast fan envelope is exactly that.
- **Costs → amber** — already used as the table accent for emphasis in cost tables.
- **Records → slate (`--border-strong`)** — neutral; Records has no semantic colour.
- **MQTT → emerald** — connection health uses emerald already.
- **Dashboard tank panel → blue** — primary lane.

Decorative use of these colours on charts or stat cards remains forbidden; only the 3 px accent strip and the page-label text use the page colour.

### Typography

- **UI:** Inter (system-stack fallback).
- **Numbers in tables / timestamps / cron / topics / payloads:** JetBrains Mono. Tabular figures (`font-variant-numeric: tabular-nums`) so columns align at the decimal.
- **Density:** tight. `text-sm` body, `text-xs` labels. No spacious dashboards — sensor data wants information density.

### Chart vocabulary (single source of truth)

ECharts is the only chart engine, with one registered theme (`kerotrack-dark`) imported by every chart. The vocabulary is closed:

| Chart | Where | Why |
|---|---|---|
| Tank silhouette (custom Svelte, no ECharts) | Dashboard hero | Tank shape *is* the data. Driven by `tank.length_cm`/`height_cm` from settings so each user's tank renders at its real proportions. |
| Sparkline area | Dashboard, Forecast snippets | "Shape over time, no axis labels" |
| Dual-axis line (oil level + temperature) | Trends | Temperature is teal, level is blue. |
| Daily consumption bars | Trends | Anomalies coloured amber inline. |
| HDD scatter | Trends | Trend line + R². |
| Calendar heatmap | Trends | Year-at-a-glance. |
| Forecast fan chart | Forecast | Median + p25/p75 + p5/p95 envelopes. |
| Step-line | Costs | Price per litre — constant between reads, never interpolated. |
| Bar chart + table | Costs | Bars are visual sort; the table is the data. |

**What we don't use:** pie charts (consumption split is a doughnut on Forecast — single exception, justified because there are exactly two segments), 3D anything, animated value transitions, gradient fills on lines (only on area charts), drop shadows, glassmorphism.

### Layout

- Persistent left sidebar (220 px), brand at top, nav middle, health pill at bottom. Active item: blue accent + 2 px left border.
- Topbar: breadcrumb left, contextual controls + status pill right.
- Main content: 24 px padding, panels in `--bg-panel` with `--border` 1 px and 10 px radius.
- Single screen on 1080 p for the Dashboard. Other pages may scroll.

### One-fact-one-home rule

A given fact has exactly one home page. The IA partitions the data deliberately:

- **Dashboard `/`** owns *right now* (current level, status pills, immediate cost figures, 14-day sparkline)
- **Trends `/trends`** owns *history* (level + temperature, daily consumption, HDD correlation, calendar heatmap)
- **Forecast `/forecast`** owns *future* (fan chart, scenario table, consumption split)
- **Costs `/costs`** owns *money* (per-period table, ppl history, summary cards)
- **Records `/records`** owns *raw rows* (paginated readings, edit, delete, refill management)
- **MQTT `/mqtt`** owns *live messages* (topic list, payload feed)
- **Settings `/settings`** owns *configuration* (DB-backed settings via accordion form)

Cross-page links exist (clicking "estimated empty date" on Dashboard deep-links into Forecast at the projection chart) — that's how relationships are surfaced without duplicating values.

### Live updates and stale-data treatment

- SSE pushes update values **in place**. No animation on value change. State changes (e.g. fill level rising on a refill) animate over 400 ms.
- New MQTT messages flash blue and settle on the MQTT page.
- If `last_reading_age > 2 × broadcast_interval_minutes`, the Dashboard hero desaturates and the status strip shows an amber "Last reading 47 min ago" pill. No modals, no toasts — the page itself communicates state.

### Number formatting

- Significant figures fixed per metric, never trailing zeros: `1106 L`, not `1106.0 L`. `4.4 L/day`, not `4.40`.
- Right-aligned in tables.
- Tabular figures in mono.

### Time formats

- Absolute timestamps for data: `2026-04-25 14:33`.
- Relative for freshness: `2 min ago`.
- Never mixed in the same view.

### Errors and empty states

- Errors live next to the affected data — no global toast. A failed price scrape shows an amber annotation next to `Current price/L`.
- Empty states explain what's missing and link to the page that fixes it ("No readings yet — check MQTT settings").
- No illustrations on empty states.

### Keyboard

Vim-style chord navigation: `g d / g t / g f / g c / g r / g m / g s` jump to Dashboard / Trends / Forecast / Costs / Records / MQTT / Settings. `?` opens a shortcut sheet.

### Component inventory

The frontend exposes exactly these components — additions go through PR review:

| Component | Used by |
|---|---|
| `TankSilhouette.svelte` | Dashboard (inside TankHeroPanel) |
| `TankHeroPanel.svelte` | Dashboard |
| `HeroShell.svelte` | All five page heroes |
| `HeroTrends.svelte` | Dashboard, Trends |
| `HeroForecast.svelte` | Dashboard, Forecast |
| `HeroCosts.svelte` | Dashboard, Costs |
| `HeroRecords.svelte` | Dashboard, Records |
| `HeroMqtt.svelte` | Dashboard, MQTT |
| `StatCard.svelte` | (deprecated; retained for migration only) |
| `LineChart.svelte` (dual-axis capable) | Trends, Costs |
| `BarChart.svelte` | Trends, Costs |
| `ScatterChart.svelte` | Trends |
| `CalendarHeatmap.svelte` | Trends |
| `ForecastFan.svelte` | Forecast (full-page) |
| `MqttFeed.svelte` | MQTT |
| `SettingsNav.svelte` + `SettingsForm.svelte` | Settings |
| `RunPanel.svelte` | Settings → Maintenance |
| `ThemeToggle.svelte` | layout |
| `Sidebar.svelte` + `KeyboardHints.svelte` | layout |

## Consequences

- New pages and components have a clear acceptance bar — review against this ADR.
- The chart vocabulary keeps the dashboard from drifting into "every component is a different chart type".
- Tank silhouette as a custom Svelte component (not ECharts) means we have one piece of bespoke SVG to maintain — but it's worth it for the data-shape match.
- The one-fact-one-home rule means cross-page navigation is more important than v1 — the routing and link work has to be deliberate.
- Light mode shipping later than dark is acceptable; if it never ships, that's fine — dark is the design target.
- Cost: every new addition is one more thing reviewers reject if it doesn't conform. That's the point.
