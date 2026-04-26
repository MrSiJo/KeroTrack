# Design — UX redesign: dashboard as control tower, page-hero gallery, settings two-pane

**Status:** Draft
**Date:** 2026-04-26
**Related:** [`docs/adr/0004-frontend-design-language.md`](../../adr/0004-frontend-design-language.md)

## Problem

Three issues with the current frontend, ordered by user impact:

1. **Dashboard feels busy.** Nine flat stat cards with no hierarchy, three different concerns (money / physics / weather) interleaved, no narrative. The information that matters most — bars-vs-Watchman, days-to-empty, cost-to-fill at current price — has equal visual weight to "HDD this period". Status banner is a small chip. RunPanel is admin tooling crammed onto the live view.
2. **Settings is dense and cluttered.** ~45 fields across 9 groups in one tall accordion, each row carries four pieces of text (label + dotted-key + input + description). User has to scroll through groups they don't care about to reach the one they do.
3. **Pages feel repetitive.** The seven pages share chrome and components but lack distinct identity. Switching between Trends, Forecast, Costs reads as "the same panel layout, different chart". No signature widget per page.

This design addresses all three with a single coherent move: the **dashboard becomes a control tower of page-hero widgets**, and each of those widgets is *the same Svelte component* that anchors the corresponding page's header — small on dashboard, full-width on the page itself. One implementation, two sizes; page identity comes free; the dashboard becomes a navigable summary; pages get a strong signature element.

## Goals

- The dashboard's primary view fits comfortably on 1080p without crowding (per ADR-0004).
- The three headline numbers — bars (vs Watchman), days-to-empty, cost-to-fill — are immediately scannable and well-spaced.
- Each hero widget on the dashboard answers one question and links to the page that owns it.
- The five page heroes have visually distinct silhouettes so the dashboard reads as five different stories at a glance, not five sparklines.
- Settings reduces to one group's fields visible at a time, with global search.
- All changes respect the existing palette, typography, and semantic colour rule in ADR-0004.

## Non-goals

- Replacing or extending the chart engine (still ECharts + custom Svelte for the tank).
- Light-mode polish (out of scope; dark stays the design target).
- Renegotiating the IA or routing (one-fact-one-home rule stands).
- Mobile-first layout work (1080p desktop remains the design target; tiles wrap on narrow widths but mobile polish is a follow-up).
- Adding new data sources or backend endpoints; this is presentation only.

## Architecture overview

Three changes, each scoped to a clear unit:

1. **Tank hero panel** rewritten — same `TankSilhouette` component (already includes the 10-bar gauge), now placed in a panel with bars+% as a co-equal headline pair, days-to-empty and cost-to-fill as secondary headline numbers, and a status row at the bottom. RunPanel moves off the dashboard.
2. **Page-hero widgets** — five new Svelte components (`HeroTrends`, `HeroForecast`, `HeroCosts`, `HeroRecords`, `HeroMqtt`). Each takes a `size` prop (`"tile"` or `"full"`) and renders the same chart inside the appropriate envelope. The page (`/trends`, etc.) renders `<HeroX size="full" />` at the top followed by the existing detail charts; the dashboard renders `<HeroX size="tile" />` in the gallery grid.
3. **Settings page** restructured to two-pane: group sidebar on the left (with search and group counts), single group's form on the right. Per-row treatment cleaned up (key hidden until row is focused, description on a tooltip, inputs sized to type).

No backend changes. All data each hero needs is already available via existing API endpoints (`/api/readings`, `/api/forecast`, `/api/cost/by-month`, `/api/status`).

## Section A — Dashboard layout

**Shape: tank-left, hero-gallery-right** (Layout 1).

```
┌──────────────────────────┬──────────────────────────────┐
│  Tank hero panel         │  Trends tile  │ Forecast tile│
│  (5/12 cols)             │ ─────────────┼──────────────│
│                          │  Costs tile   │ Records tile │
│                          │ ─────────────┴──────────────│
│                          │  MQTT strip (full width)     │
└──────────────────────────┴──────────────────────────────┘
```

### Tank hero panel (left, 5 of 12 columns)

- Existing `TankSilhouette.svelte` (with its 10-bar vertical gauge) sits on the left of the panel.
- To the right of the gauge, three headline blocks stacked vertically with generous spacing:
  - **Headline 1 — Bars + %** at equal weight, e.g. `5/10 · 50%`. Subtitle: `612 L / 1225`. This is the first thing the eye lands on, designed to read in the same orientation as the physical Watchman gauge.
  - **Headline 2 — Days to empty.** Tones amber when `< 30`, red when `< 14`. Subtitle: estimated empty date.
  - **Headline 3 — Cost to fill.** Subtitle: `at <current> p/L`.
- Bottom strip: status pill (`Plan a refill` amber when `pct ≤ low_threshold`, `Critical level` red when `pct ≤ low_threshold * 0.5`) + last-reading freshness on the right.
- Tank panel gets a 3 px blue (`--blue`) accent on its left edge to mark it as the Dashboard's "now" panel.

### Hero gallery (right, 7 of 12 columns)

A 2-column grid of page-hero tiles plus one full-width strip at the bottom:

| Position | Hero | Page link |
|---|---|---|
| Top-left | Trends | `/trends` |
| Top-right | Forecast | `/forecast` |
| Middle-left | Costs | `/costs` |
| Middle-right | Records | `/records` |
| Bottom (full-width) | MQTT | `/mqtt` |

Each tile is clickable; clicking deep-links to the corresponding page. The MQTT strip is full-width because connection health is binary-ish and benefits from horizontal space for the message-pulse histogram.

Each tile carries a 3 px left-edge accent in the page's signature colour (Trends teal, Forecast violet, Costs amber, Records slate, MQTT emerald). The accents are within the existing semantic colour rule because each accent is the colour that already represents that page's data type (teal = temperature lane → Trends owns temperature; violet = secondary chart series → Forecast envelope already uses violet in ADR-0004; amber = caution but also the existing money-table accent; emerald = good news, used for MQTT-connected health).

> *Note:* the violet/Forecast and amber/Costs accents extend ADR-0004's semantic palette one step. Both are defensible (Forecast already uses violet for the secondary forecast series; Costs already uses amber for emphasis in tables) but should be called out in the implementation plan as a deliberate widening, and the ADR updated accordingly.

### What's gone

- The supporting strip of secondary stat cards (Avg daily use, Avg daily cost, Days since refill, Temperature, HDD this period). Those numbers move to where they belong: avg daily use and HDD onto the Trends page; avg daily cost onto Costs; days since refill onto Records (or the tank panel's bottom strip if it earns a place).
- RunPanel — moves to a small overflow menu in the topbar, or to a Settings → Maintenance pane. Manual scrape isn't part of "now".

## Section B — Page hero widgets

Five new components, one per page. Each takes `size: "tile" | "full"` and renders the same chart with the same data; only the chrome and density differ.

**Locked vocabulary — one shape per hero:**

| Page | Hero shape | Headline | What it answers |
|---|---|---|---|
| Trends | Area-line (level over 30d, refill markers) | `−210 L` consumed | "What happened recently?" |
| Forecast | Fan envelope (median + p25/p75) | `~ 21 Jul` empty date | "When will I run out, with what confidence?" |
| Costs | Column bars (£ per month, 12 months, current month accent) | `£167 ▼3p` | "What did I spend, is this month unusual?" |
| Records | Event timeline (dots on a line — refill green, anomaly amber, normal blue) | `47 readings + 1 refill` | "What happened lately?" |
| MQTT | Pulse histogram (messages per minute, last 60 min) | `● Connected · 2 min ago` | "Is data flowing, and how steady?" |

The five silhouettes are deliberately different shapes (curved area, widening cone, vertical bars, horizontal lane of dots, dense histogram) so the dashboard does not read as "five sparklines in different colours".

### Tile size (dashboard)

- Header row: page label (in accent colour) + range tag.
- Headline number on one line.
- Chart roughly 30–40 px tall.
- Footer subtitle with a single supporting fact.
- No axis labels, no legend.
- Whole tile is clickable.

### Full size (page header)

- Header row: page label + headline number large + range chips (7d/30d/90d/365d for charts that support range).
- Chart roughly 80–120 px tall, with axis labels, hover tooltip, and (if applicable) refill/anomaly callouts.
- Sits as the first panel on the corresponding page; existing detail charts (e.g. Trends' calendar heatmap, scatter, daily bars) follow underneath.

### Data sources

All heroes read from existing API endpoints. No new backend work; if any hero needs a derived figure that isn't already on the API, the implementation plan should call it out as a dependency rather than the spec inventing one.

## Section C — Settings two-pane

```
┌─────────────┬───────────────────────────────────┐
│  Search…    │  MQTT — broker connection (10)    │
├─────────────┤  ─────────────────────────────────│
│  Tank   (6) │  Broker host    [172.16.0.21]    │
│ ▶MQTT  (10) │  Broker port    [1883]           │
│  Schedule(4)│  Username       [kerotrack]      │
│  Boiler (10)│  Password [secret] ••••••••       │
│  Prices (4) │  Topic prefix   [oiltank/]       │
│  Alerts (2) │  ...                              │
│  Notifs (4) │                                   │
│  Currency(2)│                                   │
│  Web    (3) │                                   │
└─────────────┴───────────────────────────────────┘
                                          [Save (n)]
```

### Left pane — group navigator

- Search box at top filters fields across all groups (matches on label and key).
- Group list below with name + count badge (`MQTT (10)`).
- Active group: blue left-edge accent + elevated background, mirroring the sidebar nav pattern.
- Selecting a group swaps the right pane.
- The change-password form gets its own group entry at the bottom (`Account`) so it's discoverable and consistent.

### Right pane — single group's form

- Group header: name, count, short description.
- Fields rendered in a grid with the label on the left (140 px) and the input on the right.
- **Per-row cleanups (apply to both panes regardless):**
  - Dotted key (`tank.capacity_l`) hidden by default; visible on row hover or focus, or behind a small "Show keys" toggle in the page header.
  - Description text moves to a `(ⓘ)` icon next to the label, revealed on hover/focus.
  - Inputs sized to value type (port number is 80 px not full-width, capacity is 100 px, etc.).
- Save button stays in the topbar (sticky), with the dirty-field count badge as today.

### Search

- Searching reveals a flat list of matching fields across all groups, with the group name as a small tag on each row. Selecting a result jumps to that group with the row highlighted.

## Section D — What changes per file (high-level)

> *This is a sketch for the implementation plan to refine. Spec is intentionally not pinning line-level edits.*

- `frontend/src/routes/+page.svelte` — rewrite to two-column grid; remove the 9-card stat block, the status pills row, and the RunPanel.
- `frontend/src/lib/components/TankSilhouette.svelte` — no logic changes; consumed inside a new wrapper that lays out bars+% headline + secondary numbers.
- New: `HeroTrends.svelte`, `HeroForecast.svelte`, `HeroCosts.svelte`, `HeroRecords.svelte`, `HeroMqtt.svelte`. Each takes `size` prop and reuses the existing chart components where possible (`LineChart`, `ForecastFan`, `BarChart`).
- `frontend/src/routes/trends/+page.svelte`, `forecast/+page.svelte`, `costs/+page.svelte`, `records/+page.svelte`, `mqtt/+page.svelte` — render `<HeroX size="full" />` as the first panel, push existing content below.
- `frontend/src/routes/settings/+page.svelte` — split into `SettingsNav.svelte` (left) and `SettingsForm.svelte` (right), with shared search store.
- `RunPanel.svelte` — move to a topbar overflow menu (or to a Settings → Maintenance accordion entry).
- `docs/adr/0004-frontend-design-language.md` — small amendment: violet and amber accents now allowed as page-identity accents alongside their existing semantic uses; component inventory updated.

## Open questions / deferred to implementation plan

- Exact behaviour of the topbar overflow menu housing RunPanel (or whether RunPanel moves to Settings instead).
- Whether MQTT pulse histogram fetches a small `/api/mqtt/recent` summary or computes it from the existing `/api/mqtt/feed` SSE stream client-side.
- Refill marker and anomaly callout shapes at full size (the implementation plan should pick consistent affordances, e.g. green dot + tooltip for refills, amber dot for anomalies).
- Whether the Records hero should bucket events by day or show them on a continuous time axis (continuous reads more honestly; bucketed is easier to scan).
- Settings: search input debounce, keyboard shortcut to focus, whether to persist the last-selected group in `localStorage`.

## Tests / acceptance criteria

- Dashboard renders five hero tiles + tank panel on a 1080p viewport without scrolling.
- Each hero tile, when clicked, navigates to its corresponding page and the page header shows the same hero rendered at full size with consistent data.
- Tank hero shows bars+% as equal-weight headline; days-to-empty tones amber `< 30 d` and red `< 14 d`.
- Settings: selecting a group in the left nav swaps the right pane; search filters across groups; save badge counts dirty fields.
- All five hero silhouettes are visually distinct at tile size (manual eye-check; no automated test for "looks different").
- Existing security tests, e2e smoke, and unit tests still pass — this is a presentation-layer change.
- A new e2e test asserts dashboard → click each hero tile → land on correct route.

## Migration / rollout

Single PR, no feature flag. The change is presentation-only and the v2 frontend has no production users yet to disturb. The deploy ritual (CLAUDE.md) applies: commit → push → `docker compose up` on the deploy host → `curl /api/health`.
