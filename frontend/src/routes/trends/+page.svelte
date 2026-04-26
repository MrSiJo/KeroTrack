<script lang="ts">
  import { onMount } from "svelte";

  import BarChart from "$lib/components/BarChart.svelte";
  import CalendarHeatmap from "$lib/components/CalendarHeatmap.svelte";
  import LineChart from "$lib/components/LineChart.svelte";
  import ScatterChart from "$lib/components/ScatterChart.svelte";
  import { api } from "$lib/api";
  import type { Reading } from "$lib/types/api";

  type RangeOption = { label: string; days: number };

  const RANGES: RangeOption[] = [
    { label: "7d", days: 7 },
    { label: "30d", days: 30 },
    { label: "90d", days: 90 },
    { label: "365d", days: 365 },
  ];

  let selectedDays = $state<number>(30);
  let readings = $state<Reading[]>([]);
  let yearReadings = $state<Reading[]>([]);
  let loading = $state(false);
  let yearLoading = $state(false);
  let error = $state<string | null>(null);

  function isoDaysAgo(days: number): string {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - days);
    // Backend accepts YYYY-MM-DD HH:MM:SS strings; truncate to date.
    return d.toISOString().slice(0, 10);
  }

  function dayKey(s: string): string {
    return s.length >= 10 ? s.slice(0, 10) : s;
  }

  async function loadRange(days: number): Promise<void> {
    loading = true;
    error = null;
    try {
      const since = `${isoDaysAgo(days)} 00:00:00`;
      const resp = await api.readings({
        since,
        order: "asc",
        limit: Math.min(days * 50 + 200, 10000),
      });
      readings = resp.items ?? [];
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      error = msg;
      readings = [];
    } finally {
      loading = false;
    }
  }

  async function loadYear(): Promise<void> {
    yearLoading = true;
    try {
      const since = `${isoDaysAgo(365)} 00:00:00`;
      const resp = await api.readings({
        since,
        order: "asc",
        limit: 10000,
      });
      yearReadings = resp.items ?? [];
    } catch {
      yearReadings = [];
    } finally {
      yearLoading = false;
    }
  }

  onMount(() => {
    void loadRange(selectedDays);
    void loadYear();
  });

  function chooseRange(days: number): void {
    if (days === selectedDays) return;
    selectedDays = days;
    void loadRange(days);
  }

  // ---------- derived series -----------------------------------------

  // Level + temperature line series (one point per reading)
  let levelTempSeries = $derived(
    readings.map((r) => ({
      x: r.date,
      y1: r.litres_remaining ?? null,
      y2: r.temperature ?? null,
    })),
  );

  // Daily consumption: sum litres_used_since_last per calendar day,
  // ignoring negative values (refill spikes).
  let dailyConsumption = $derived.by(() => {
    const buckets = new Map<string, number>();
    for (const r of readings) {
      const used = r.litres_used_since_last;
      if (used == null || !Number.isFinite(used) || used <= 0) continue;
      const k = dayKey(r.date);
      buckets.set(k, (buckets.get(k) ?? 0) + used);
    }
    const entries = Array.from(buckets.entries()).sort(([a], [b]) =>
      a < b ? -1 : a > b ? 1 : 0,
    );
    const values = entries.map(([, v]) => v);
    const mean =
      values.length > 0 ? values.reduce((s, v) => s + v, 0) / values.length : 0;
    const threshold = mean * 1.5;
    return entries.map(([date, value]) => ({
      x: date,
      y: Number(value.toFixed(3)),
      anomaly: mean > 0 && value > threshold,
    }));
  });

  // HDD vs daily-litres scatter — pair readings' daily HDD with same-day consumption.
  let hddScatter = $derived.by(() => {
    const consByDay = new Map<string, number>();
    for (const d of dailyConsumption) {
      consByDay.set(String(d.x), d.y);
    }
    const hddByDay = new Map<string, number>();
    for (const r of readings) {
      const hdd = r.heating_degree_days;
      if (hdd == null || !Number.isFinite(hdd)) continue;
      const k = dayKey(r.date);
      // Take the latest non-null HDD seen for the day.
      hddByDay.set(k, hdd);
    }
    const points: { x: number; y: number }[] = [];
    for (const [day, lit] of consByDay) {
      const hdd = hddByDay.get(day);
      if (hdd == null) continue;
      if (!Number.isFinite(hdd) || !Number.isFinite(lit)) continue;
      points.push({ x: hdd, y: lit });
    }
    return points;
  });

  // Year heatmap data: daily consumption from full year window.
  let yearDaily = $derived.by(() => {
    const buckets = new Map<string, number>();
    for (const r of yearReadings) {
      const used = r.litres_used_since_last;
      if (used == null || !Number.isFinite(used) || used <= 0) continue;
      const k = dayKey(r.date);
      buckets.set(k, (buckets.get(k) ?? 0) + used);
    }
    return Array.from(buckets.entries()).map(([date, value]) => ({
      date,
      value: Number(value.toFixed(3)),
    }));
  });

  let currentYear = $derived(new Date().getUTCFullYear());
</script>

<div class="space-y-6">
  <header class="flex flex-wrap items-center justify-between gap-3">
    <div>
      <h1 class="text-lg font-semibold">Trends</h1>
      <p class="text-xs text-text-muted">
        Level, daily use, weather correlation and a year-at-a-glance heatmap.
      </p>
    </div>

    <div
      role="radiogroup"
      aria-label="Date range"
      class="inline-flex overflow-hidden rounded border border-border bg-bg-panel"
    >
      {#each RANGES as r (r.days)}
        <button
          type="button"
          role="radio"
          aria-checked={selectedDays === r.days}
          class={`px-3 py-1.5 text-xs font-mono transition-colors ${
            selectedDays === r.days
              ? "bg-brand-blue text-white"
              : "text-text-muted hover:bg-bg-elev hover:text-text"
          }`}
          onclick={() => chooseRange(r.days)}
        >
          {r.label}
        </button>
      {/each}
    </div>
  </header>

  {#if error}
    <div
      class="rounded border border-brand-red/40 bg-red-950/40 px-3 py-2 text-xs text-brand-red"
    >
      Failed to load readings: {error}
    </div>
  {/if}

  <!-- 1. Level + temperature -->
  <section class="rounded-lg border border-border bg-bg-panel p-4">
    <div class="mb-2 flex items-center justify-between">
      <h2 class="text-sm font-semibold">Level + temperature</h2>
      <span class="text-[11px] text-text-subtle">
        {readings.length} samples · last {selectedDays} days
      </span>
    </div>
    {#if loading}
      <div
        class="flex h-[320px] items-center justify-center text-xs text-text-subtle"
      >
        Loading…
      </div>
    {:else}
      <LineChart
        data={levelTempSeries}
        y1Label="Litres"
        y2Label="°C"
        height="320px"
      />
    {/if}
  </section>

  <!-- 2. Daily consumption -->
  <section class="rounded-lg border border-border bg-bg-panel p-4">
    <div class="mb-2 flex items-center justify-between">
      <h2 class="text-sm font-semibold">Daily consumption</h2>
      <span class="text-[11px] text-text-subtle">
        amber bars exceed 1.5× period mean
      </span>
    </div>
    {#if loading}
      <div
        class="flex h-[320px] items-center justify-center text-xs text-text-subtle"
      >
        Loading…
      </div>
    {:else}
      <BarChart data={dailyConsumption} yLabel="Litres / day" height="320px" />
    {/if}
  </section>

  <!-- 3. HDD vs consumption -->
  <section class="rounded-lg border border-border bg-bg-panel p-4">
    <div class="mb-2 flex items-center justify-between">
      <h2 class="text-sm font-semibold">HDD vs consumption</h2>
      <span class="text-[11px] text-text-subtle">least-squares fit</span>
    </div>
    {#if loading}
      <div
        class="flex h-[320px] items-center justify-center text-xs text-text-subtle"
      >
        Loading…
      </div>
    {:else}
      <ScatterChart
        points={hddScatter}
        xLabel="Heating degree days"
        yLabel="Litres / day"
        height="320px"
      />
    {/if}
  </section>

  <!-- 4. Calendar heatmap (always 365d window regardless of picker) -->
  <section class="rounded-lg border border-border bg-bg-panel p-4">
    <div class="mb-2 flex items-center justify-between">
      <h2 class="text-sm font-semibold">Calendar heatmap</h2>
      <span class="text-[11px] text-text-subtle">
        daily consumption · {currentYear}
      </span>
    </div>
    {#if yearLoading}
      <div
        class="flex h-[200px] items-center justify-center text-xs text-text-subtle"
      >
        Loading…
      </div>
    {:else}
      <CalendarHeatmap
        data={yearDaily}
        year={currentYear}
        height="200px"
      />
    {/if}
  </section>
</div>
