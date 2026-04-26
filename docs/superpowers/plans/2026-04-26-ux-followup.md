# UX Redesign Follow-Up Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to execute task-by-task.

**Goal:** Address feedback from the first deploy of the UX redesign — frontend polish, settings ergonomics, light-theme bug, and a Records-page filter pass. Backend issues raised during review are catalogued at the bottom for a separate effort.

**Architecture:** Pure frontend changes on the `ux-redesign` branch. No new endpoints. The existing `api.resetSetting()` and `def.description` plumbing already supports the new tooltip + reset features.

**Tech Stack:** SvelteKit 5, TypeScript, Tailwind. May add `cronstrue` (~10 KB) for human-readable cron labels.

---

## Frontend — to do now

### Task FE1: Light-theme tank shell

**Problem:** `TankSilhouette.svelte` hard-codes `fill="#0a0f1c"` (the dark page background) on the outer shell rect, so the tank looks like a black box on a light background.

**File:** `frontend/src/lib/components/TankSilhouette.svelte`

**Change:** Replace the hard-coded `fill="#0a0f1c"` and `stroke="#334155"` on the shell `<rect>` with theme-aware values driven by CSS vars. Tailwind defines `--bg-page` and `--border-strong` with R G B triplets; the simplest pattern is to set the SVG attribute via inline style using `rgb(var(...))`.

Replace the shell `<rect>` block (around lines 80–90) with:

```svelte
<rect
  x="2"
  y="2"
  width={w - 4}
  height={h - 4}
  rx="14"
  ry="14"
  style="fill: rgb(var(--bg-page)); stroke: rgb(var(--border-strong));"
  stroke-width="2"
/>
```

Verify visually after deploy: dark theme should look identical, light theme should show a near-white tank shell.

Commit message: `fix(ui): TankSilhouette shell uses theme-aware bg + border colours`

---

### Task FE2: MQTT settings explicit ordering

**Problem:** MQTT settings render in schema order (broker, port, username, password, then a mix). User wants: broker → port → username → password → topics → timeouts/intervals.

**File:** `frontend/src/lib/components/SettingsForm.svelte`

**Change:** Introduce a per-group ordering map. When the active group has an explicit order list, sort the visible items by that list (unknown keys after).

Add to script:

```typescript
const GROUP_ORDER: Record<string, string[]> = {
  mqtt: [
    "mqtt.broker",
    "mqtt.port",
    "mqtt.username",
    "mqtt.password",
    "mqtt.topic_readings",
    "mqtt.topic_analytics",
    "mqtt.topic_costanalysis",
    "mqtt.broadcast_interval_minutes",
    "mqtt.timeout_minutes",
  ],
};

function applyOrder(items: SettingItem[], group: string): SettingItem[] {
  const order = GROUP_ORDER[group];
  if (!order) return items;
  const idx = (k: string) => {
    const i = order.indexOf(k);
    return i === -1 ? Number.MAX_SAFE_INTEGER : i;
  };
  return [...items].sort((a, b) => idx(a.key) - idx(b.key));
}
```

Modify `visibleItems` to apply order when not in search mode:

```typescript
let visibleItems = $derived(() => {
  const q = $search.trim().toLowerCase();
  if (q) { /* unchanged */ }
  if ($activeGroup === "account") return [];
  if ($activeGroup === "maintenance") return [];
  return applyOrder($settings.groups[$activeGroup] ?? [], $activeGroup);
});
```

Commit message: `ui: explicit field order for MQTT settings group`

---

### Task FE3: Web group — theme dropdown + hide Page title

**Problem:** `web.theme_default` is rendered as a free-text input. User wants a dropdown of `dark`/`light`/`system`. `web.title` is configurable but unused — hide it from the UI.

**File:** `frontend/src/lib/components/SettingsForm.svelte`

**Changes:**

1. Filter `web.title` out of `visibleItems` for the web group. Add to `applyOrder` filter step or do it at the top of visibleItems:

```typescript
const HIDDEN_KEYS = new Set<string>(["web.title"]);
```

In the `visibleItems` computation, filter `i => !HIDDEN_KEYS.has(i.key)` before returning the group items (and search results too).

2. Add a custom branch in the field render switch for `web.theme_default`. Above the existing `{#if item.value_type === "bool"}` chain, add:

```svelte
{#if item.key === "web.theme_default"}
  <select
    class="w-32 rounded border border-border bg-bg-elev px-2 py-1 text-xs"
    value={display(item) as string}
    onchange={(e) => onChange(item.key, (e.currentTarget as HTMLSelectElement).value)}
  >
    <option value="dark">Dark</option>
    <option value="light">Light</option>
    <option value="system">System (auto)</option>
  </select>
{:else if item.value_type === "bool"}
  ...existing...
```

(Convert the existing `{#if}` chain so `{#if item.key === "web.theme_default"}` is the first branch followed by `{:else if ...}`.)

Commit message: `ui: web.theme_default rendered as dropdown; hide unused web.title`

---

### Task FE4: Per-setting tooltip + per-page reset

**Problem:** Tooltip on the (ⓘ) icon is currently a native `title` attribute (slow to appear, no styling). Per-page reset button missing.

**File:** `frontend/src/lib/components/SettingsForm.svelte`

**Changes:**

1. Replace the `<span title={...}>` pattern with a small CSS-only popover. Approach: keep markup minimal; use `group/info` Tailwind classes so a hidden label appears on hover/focus. Replace the existing `<span title="...">` block with:

```svelte
<span class="inline-flex items-center gap-1">
  {def?.label ?? item.label}
  {#if def?.description}
    <span class="group/info relative inline-block cursor-help text-text-subtle" tabindex="0" aria-label={def.description}>
      ⓘ
      <span class="pointer-events-none invisible absolute left-1/2 top-full z-10 mt-1 w-64 -translate-x-1/2 rounded border border-border bg-bg-elev px-2 py-1 text-[11px] text-text shadow-lg group-hover/info:visible group-focus/info:visible">
        {def.description}
      </span>
    </span>
  {/if}
</span>
```

(The `group/info` is a named Tailwind group — check if Tailwind config supports named groups. If not, use plain `group` plus `group-hover:`.)

2. Add a per-page reset button to the `<header>` of the right pane. Modify the header in `SettingsForm.svelte`:

```svelte
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
  {#if !$search.trim() && $activeGroup !== "account" && $activeGroup !== "maintenance"}
    <button
      type="button"
      class="rounded border border-border px-2 py-1 text-[11px] text-text-muted hover:border-border-strong hover:text-text disabled:opacity-50"
      onclick={resetGroup}
      disabled={resettingGroup}
    >
      {resettingGroup ? "Resetting…" : `Reset ${$activeGroup}`}
    </button>
  {/if}
</header>
```

3. Add the reset handler to the script block:

```typescript
let resettingGroup = $state(false);

async function resetGroup() {
  const items = $settings.groups[$activeGroup] ?? [];
  if (!items.length) return;
  if (!confirm(`Reset all ${items.length} ${$activeGroup} settings to their default values? This is immediate; pending unsaved changes will be discarded.`)) {
    return;
  }
  resettingGroup = true;
  try {
    for (const item of items) {
      await api.resetSetting(item.key);
    }
    await settings.refresh();
  } catch (err) {
    // surface via the existing error channel
    console.error("reset failed", err);
  } finally {
    resettingGroup = false;
  }
}
```

(Import `settings` from `$lib/stores/settings` if not already.)

Commit message: `ui: real CSS popover tooltip on settings rows + per-group reset button`

---

### Task FE5: Apprise URL friendly editor

**Problem:** `notifications.apprise_urls` is a JSON array of strings, currently rendered as a textarea showing `["gotify://…"]`. User wants one URL per line, no brackets/quotes.

**File:** `frontend/src/lib/components/SettingsForm.svelte`

**Change:** Add a custom branch above the generic `value_type === "json"` branch for keys whose value is a list of strings (apprise URLs being the canonical case). Detect by key name to keep the narrow contract:

```svelte
{#if item.key === "notifications.apprise_urls"}
  {@const lines = Array.isArray(display(item)) ? (display(item) as string[]).join("\n") : ""}
  <textarea
    class="w-full rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
    rows="3"
    placeholder="One URL per line — e.g. gotify://192.168.1.10/AbC123"
    oninput={(e) => {
      const raw = (e.currentTarget as HTMLTextAreaElement).value;
      const arr = raw.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
      onChange(item.key, arr);
    }}
    >{lines}</textarea
  >
{:else if item.value_type === "json"}
  ...existing JSON branch...
```

Commit message: `ui: apprise URLs render as one-per-line, hide JSON brackets/quotes`

---

### Task FE6: Cron natural-language label

**Problem:** Cron expressions in Schedule settings are technical. User wants a human-readable label alongside the input.

**Approach:** Add `cronstrue` dependency (small, no transitive baggage). Render its translation as a faint line above the existing "Next 3 fires" output.

**Files:**
- `frontend/package.json` (add dep)
- `frontend/src/lib/components/SettingsForm.svelte`

**Changes:**

1. Add dep: `cd frontend && npm install --save cronstrue`
2. In `SettingsForm.svelte`, import:

```typescript
import cronstrue from "cronstrue";

function describeCron(expr: string): string {
  if (!expr || typeof expr !== "string") return "";
  try {
    return cronstrue.toString(expr.trim(), { use24HourTimeFormat: true });
  } catch {
    return "";
  }
}
```

3. In the cron branch, after the input and before "Next 3 fires", insert:

```svelte
{#if cronValue.trim()}
  {@const human = describeCron(cronValue)}
  {#if human}
    <div class="mt-1 text-[11px] text-text-muted">{human}</div>
  {/if}
{/if}
```

Commit message: `ui: human-readable cron description above each cron input`

---

### Task FE7: Trends calendar heatmap window

**Problem:** Heatmap only shows Jan 2026 even though there are 4 months of data.

**Investigate first** — open `frontend/src/lib/components/CalendarHeatmap.svelte` and the Trends page's data loading. Most likely fixes:
- The "year readings" fetch hits `/api/readings` with too small a `limit` and the most recent rows are dropped (older first/asc paging boundary).
- Or the heatmap's date-bucketing logic uses `since`/`until` that haven't been refreshed.

**File:** likely `frontend/src/routes/trends/+page.svelte` (the `loadYear` function)

**Approach:** Read the function, check the `limit` param and the date window. If `limit` is e.g. 3000 and there are 4000 readings in the year, ascending order would drop the recent ones. Bump the limit, or add a server-side aggregation.

If the issue is more involved (server-side missing days), surface it as a backend task instead.

Commit message: `fix(ui): Trends calendar heatmap fetches a wider window of readings`

---

### Task FE8: Records page filters

**Problem:** Records page has no filters. User wants: date range (date+time), litres, percentage, used (refill/anomaly flag), temperature, refill/leak.

**File:** `frontend/src/routes/records/+page.svelte`

**Approach:** Add a sticky filter bar at the top of the page (under the new HeroRecords). Two server-side fields (`since`, `until`) hit the API; the rest are applied client-side to the fetched rows.

Filter UI fields:
- Date range — two `<input type="datetime-local">` fields. On change, refetch readings.
- Litres — min/max number inputs. Client-side filter on `litres_remaining`.
- Percentage — min/max number inputs. Client-side filter on `percentage_remaining`.
- Temperature — min/max number inputs. Client-side filter on `temperature`.
- Refill — three-state checkbox (any / yes / no) → maps to `refill_detected === "y"` filter.
- Leak — same three-state pattern.

Wire into a small `<FiltersBar>` subcomponent if it grows past ~80 lines. The Records page table renders the filtered list.

Persist filter state in the URL query string for shareability (`?since=…&until=…&pct_min=…`). Use `goto` with `replaceState: true` to update.

Commit message: `feat(ui): Records page filter bar — date range + litres/%/temp/refill/leak`

---

### Task FE9: Onboarding wizard

**Problem:** After initial setup (username/password) the user lands on a dashboard with no MQTT broker configured, no tank dimensions, no boiler defaults. They must hunt through Settings.

**Approach:** New route `/onboarding` shown after first successful login when key settings are still at defaults (or empty). Present 3 steps: MQTT, Tank, Boiler. Submit writes to `/api/settings`. Last step redirects to `/`.

**Files:**
- Create: `frontend/src/routes/onboarding/+page.svelte`
- Modify: `frontend/src/routes/+layout.svelte` — redirect to `/onboarding` if `mqtt.broker === "localhost"` or empty (same heuristic for tank.capacity_l, etc.)

**Detection heuristic:** Treat the user as needing onboarding when ALL of these are at their defaults:
- `mqtt.broker === "localhost"`
- `mqtt.username === ""`
- `notifications.apprise_urls` is empty array

(Tank/boiler defaults are pre-filled with sensible values from the schema — if the user hasn't changed them, that's fine.)

Each step is a card with the relevant subset of fields, sensible defaults pre-filled, and a Next button. Final step has a "Save & finish" button.

Commit message: `feat(ui): post-setup onboarding wizard — MQTT, tank, boiler`

---

## Backend — deferred (separate effort, a new branch off main once ux-redesign lands)

### BE1: `/api/costs/periods` returns full monthly series

**Symptom:** HeroCosts only shows two bars (Apr 2025 + Oct 2024) because the endpoint returns those two periods.

**Fix:** Backend `cost_service` (or wherever `costs/periods` is built) should emit one row per calendar month within the data window — even months with zero cost. Frontend already uses `slice(-12)` so giving it 12 months is enough.

**Files (likely):** `backend/kerotrack/api/routes/cost.py` or similar — search for the `/api/costs/periods` route handler.

### BE2: Daily consumption baseline (hot water)

**Symptom:** Daily consumption bar chart on Trends has gaps on days with no level drop, even though the boiler runs hot water year-round.

**Fix:** Consumption aggregator should emit a non-zero baseline derived from the boiler's hot-water profile (configured via `boiler.*` settings) when the level reading is flat. Or — alternative — interpolate consumption between sparse readings rather than requiring a level drop on each day.

Investigate `backend/kerotrack/analysis/consumption.py`.

### BE3: Forecast heating-vs-hot-water split

**Symptom:** The doughnut on Forecast shows 100% heating, 0% hot water.

**Likely cause:** Same root as BE2 — if the consumption aggregator never assigns baseline draw to hot water, the split will always be heating-only. Fix BE2 first; this should resolve as a downstream effect.

---

## Execution order

FE1 → FE2 → FE3 → FE4 → FE5 → FE6 → FE7 (investigate, may bounce to BE) → FE8 → FE9.

Build + redeploy after FE6 (mid-checkpoint), then again after FE9 (final). User browses + reports any new issues; small follow-up fixes can be amended onto the same commits or layered.
