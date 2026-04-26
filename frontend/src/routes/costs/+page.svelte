<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import * as echarts from "echarts";

  import BarChart from "$lib/components/BarChart.svelte";
  import LineChart from "$lib/components/LineChart.svelte";
  import StatCard from "$lib/components/StatCard.svelte";
  import { KEROTRACK_DARK_THEME } from "$lib/charts/theme";
  import { api } from "$lib/api";
  import type { Reading } from "$lib/types/api";

  type Period = {
    start_date?: string;
    end_date?: string;
    days?: number;
    total_consumption?: number;
    total_cost?: number;
    daily_cost?: number;
    refill_amount_liters?: number;
    refill_ppl?: number;
    refill_cost?: number;
    cost_per_hdd?: number;
    consumption_per_hdd?: number;
    total_hdd?: number;
    used_actual_cost?: boolean | number | null;
    [k: string]: unknown;
  };

  type LinePoint = { x: string | number; y1: number; y2?: number };
  type BarPoint = { x: string | number; y: number; anomaly?: boolean };

  let summary = $state<Record<string, unknown> | null>(null);
  let periods = $state<Period[]>([]);
  let pplHistory = $state<LinePoint[]>([]);
  let perPeriodCosts = $state<BarPoint[]>([]);
  let efficiencyEl: HTMLDivElement | null = $state(null);
  let efficiencyChart: echarts.ECharts | null = null;
  let error = $state<string | null>(null);

  function fmtCost(n: unknown): string {
    if (typeof n !== "number" || !Number.isFinite(n)) return "—";
    return n.toFixed(2);
  }

  function isTruthy(v: unknown): boolean {
    if (v === null || v === undefined) return false;
    if (typeof v === "boolean") return v;
    if (typeof v === "number") return v !== 0;
    if (typeof v === "string") {
      const s = v.toLowerCase();
      return s === "true" || s === "1" || s === "yes";
    }
    return false;
  }

  function topQuartileThreshold(values: number[]): number {
    if (values.length === 0) return Number.POSITIVE_INFINITY;
    const sorted = [...values].sort((a, b) => a - b);
    // 75th percentile (nearest-rank)
    const idx = Math.max(0, Math.ceil(0.75 * sorted.length) - 1);
    return sorted[idx];
  }

  function buildPplHistory(items: Reading[]): LinePoint[] {
    const out: LinePoint[] = [];
    for (const r of items) {
      const ppl = r.current_ppl;
      if (typeof ppl !== "number" || !Number.isFinite(ppl)) continue;
      const x = (r.date ?? "").slice(0, 10);
      if (!x) continue;
      out.push({ x, y1: ppl });
    }
    return out;
  }

  function buildPerPeriodCosts(items: Period[]): BarPoint[] {
    const dailyCosts = items
      .map((p) => (typeof p.daily_cost === "number" ? p.daily_cost : null))
      .filter((v): v is number => v !== null && Number.isFinite(v));
    const threshold = topQuartileThreshold(dailyCosts);
    return items
      .filter(
        (p) => typeof p.total_cost === "number" && Number.isFinite(p.total_cost),
      )
      .map((p) => {
        const x = p.end_date ?? p.start_date ?? "";
        const y = Number(p.total_cost);
        const dc = typeof p.daily_cost === "number" ? p.daily_cost : -Infinity;
        return { x, y, anomaly: dc >= threshold } as BarPoint;
      });
  }

  function buildEfficiencyOption(items: Period[]): echarts.EChartsOption {
    // Horizontal bars: cost_per_hdd (£/HDD) and consumption_per_hdd (L/HDD).
    const labels: string[] = items.map((p) => p.end_date ?? p.start_date ?? "");
    const cost = items.map((p) =>
      typeof p.cost_per_hdd === "number" && Number.isFinite(p.cost_per_hdd)
        ? Number(p.cost_per_hdd)
        : 0,
    );
    const cons = items.map((p) =>
      typeof p.consumption_per_hdd === "number" &&
      Number.isFinite(p.consumption_per_hdd)
        ? Number(p.consumption_per_hdd)
        : 0,
    );

    return {
      animation: false,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
      },
      legend: {
        data: ["Cost £/HDD", "Litres/HDD"],
        top: 4,
        right: 12,
      },
      grid: { top: 36, right: 80, bottom: 24, left: 110 },
      xAxis: [
        { type: "value", name: "£/HDD", position: "bottom" },
        {
          type: "value",
          name: "L/HDD",
          position: "top",
          splitLine: { show: false },
        },
      ],
      yAxis: {
        type: "category",
        data: labels,
        inverse: true,
        axisLabel: {
          formatter: (val: string) => (val.length >= 10 ? val.slice(0, 7) : val),
        },
      },
      series: [
        {
          name: "Cost £/HDD",
          type: "bar",
          data: cost,
          xAxisIndex: 0,
          itemStyle: { color: "#3b82f6" },
          barMaxWidth: 14,
        },
        {
          name: "Litres/HDD",
          type: "bar",
          data: cons,
          xAxisIndex: 1,
          itemStyle: { color: "#2dd4bf" },
          barMaxWidth: 14,
        },
      ],
    };
  }

  function renderEfficiency(): void {
    if (!efficiencyEl || periods.length === 0) return;
    if (!efficiencyChart) {
      efficiencyChart = echarts.init(efficiencyEl, KEROTRACK_DARK_THEME);
    }
    efficiencyChart.setOption(buildEfficiencyOption(periods), true);
  }

  function onResize(): void {
    efficiencyChart?.resize();
  }

  onMount(async () => {
    try {
      summary = await api.costsSummary();
    } catch (err) {
      const msg = (err as Error).message;
      if (!msg.includes("no_cost_analysis")) error = msg;
    }
    try {
      const p = await api.costPeriods();
      periods = (p.items ?? []) as Period[];
      perPeriodCosts = buildPerPeriodCosts(periods);
    } catch (err) {
      error = (err as Error).message;
    }
    try {
      const r = await api.readings({ limit: 365, order: "asc" });
      pplHistory = buildPplHistory(r.items ?? []);
    } catch (err) {
      // Non-fatal — leave empty state.
      const msg = (err as Error).message;
      if (!error) error = msg;
    }
    if (typeof window !== "undefined") {
      window.addEventListener("resize", onResize);
    }
  });

  onDestroy(() => {
    if (typeof window !== "undefined") {
      window.removeEventListener("resize", onResize);
    }
    efficiencyChart?.dispose();
    efficiencyChart = null;
  });

  $effect(() => {
    void periods;
    if (efficiencyEl && periods.length > 0) {
      renderEfficiency();
    }
  });
</script>

<div class="space-y-6">
  <h1 class="text-lg font-semibold">Costs</h1>

  {#if error}
    <p class="text-xs text-brand-red">{error}</p>
  {/if}

  {#if summary}
    <section class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatCard
        label="Avg daily"
        value={fmtCost(summary.avg_daily_cost)}
        unit="£"
      />
      <StatCard
        label="Avg monthly"
        value={fmtCost(summary.avg_monthly_cost)}
        unit="£"
      />
      <StatCard
        label="Avg annual"
        value={fmtCost(summary.avg_annual_cost)}
        unit="£"
      />
      <StatCard
        label="Refill periods"
        value={String(summary.total_refill_periods ?? "—")}
      />
    </section>
  {:else}
    <p class="text-xs text-text-muted">
      No cost analysis run yet. Charts will populate once readings + refills are
      ingested.
    </p>
  {/if}

  <!-- 1. PPL history -->
  <section class="rounded-lg border border-border bg-bg-panel">
    <header class="flex items-baseline justify-between border-b border-border px-4 py-2">
      <h2 class="text-sm font-semibold">Price per litre — history</h2>
      <span class="text-xs text-text-muted">last 365 readings</span>
    </header>
    <div class="p-3">
      {#if pplHistory.length > 0}
        <LineChart data={pplHistory} y1Label="p/L" height="280px" />
      {:else}
        <p class="px-2 py-8 text-center text-xs text-text-muted">
          No PPL history yet.
        </p>
      {/if}
    </div>
  </section>

  <!-- 2. Per-period costs -->
  <section class="rounded-lg border border-border bg-bg-panel">
    <header class="flex items-baseline justify-between border-b border-border px-4 py-2">
      <h2 class="text-sm font-semibold">Per-period costs</h2>
      <span class="text-xs text-text-muted">
        amber bars = top-quartile daily cost
      </span>
    </header>
    <div class="p-3">
      {#if perPeriodCosts.length > 0}
        <BarChart data={perPeriodCosts} yLabel="Total £" height="280px" />
      {:else}
        <p class="px-2 py-8 text-center text-xs text-text-muted">
          No completed refill periods yet.
        </p>
      {/if}
    </div>
  </section>

  <!-- 3. Energy efficiency comparison -->
  <section class="rounded-lg border border-border bg-bg-panel">
    <header class="flex items-baseline justify-between border-b border-border px-4 py-2">
      <h2 class="text-sm font-semibold">Energy efficiency comparison</h2>
      <span class="text-xs text-text-muted">cost & consumption per HDD</span>
    </header>
    <div class="p-3">
      {#if periods.length > 0}
        <div
          bind:this={efficiencyEl}
          style="width: 100%; height: {Math.max(180, periods.length * 32 + 80)}px;"
        ></div>
      {:else}
        <p class="px-2 py-8 text-center text-xs text-text-muted">
          No HDD-normalised data yet.
        </p>
      {/if}
    </div>
  </section>

  {#if periods.length}
    <div class="rounded-lg border border-border bg-bg-panel">
      <header class="border-b border-border px-4 py-2 text-sm font-semibold">
        Refill periods
      </header>
      <div class="overflow-x-auto">
        <table class="w-full text-sm tabular">
          <thead class="bg-bg-elev text-xs text-text-label">
            <tr>
              <th class="px-3 py-2 text-left">Start</th>
              <th class="px-3 py-2 text-left">End</th>
              <th class="px-3 py-2 text-right">Days</th>
              <th class="px-3 py-2 text-right">Litres</th>
              <th class="px-3 py-2 text-right">Cost £</th>
              <th class="px-3 py-2 text-right">Daily £</th>
              <th class="px-3 py-2 text-right">PPL</th>
              <th class="px-3 py-2 text-left">Source</th>
            </tr>
          </thead>
          <tbody>
            {#each periods as p}
              <tr class="border-t border-border">
                <td class="px-3 py-1.5 font-mono text-xs">{p.start_date}</td>
                <td class="px-3 py-1.5 font-mono text-xs">{p.end_date}</td>
                <td class="px-3 py-1.5 text-right font-mono">{p.days ?? "—"}</td>
                <td class="px-3 py-1.5 text-right font-mono"
                  >{fmtCost(p.total_consumption)}</td
                >
                <td class="px-3 py-1.5 text-right font-mono">{fmtCost(p.total_cost)}</td>
                <td class="px-3 py-1.5 text-right font-mono">{fmtCost(p.daily_cost)}</td>
                <td class="px-3 py-1.5 text-right font-mono">{fmtCost(p.refill_ppl)}</td>
                <td class="px-3 py-1.5 text-xs">
                  {#if isTruthy(p.used_actual_cost)}
                    <span
                      class="inline-flex items-center gap-1 rounded border border-brand-emerald/40 bg-brand-emerald/10 px-1.5 py-0.5 text-[10px] font-medium text-brand-emerald"
                      title="Cost calculated from invoiced refill amount"
                    >
                      <span aria-hidden="true">✓</span> invoiced
                    </span>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
</div>
