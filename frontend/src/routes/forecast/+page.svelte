<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import * as echarts from "echarts";

  import StatCard from "$lib/components/StatCard.svelte";
  import ForecastFan from "$lib/components/ForecastFan.svelte";
  import { api } from "$lib/api";
  import { KEROTRACK_DARK_THEME } from "$lib/charts/theme";
  import type { AnalysisResult, Reading } from "$lib/types/api";

  type HistoryPoint = { date: string; litres: number };
  type Scenario = {
    label: string;
    perDayL: number;
    daysRemaining: number | null;
    emptyDate: string | null;
    note?: string;
  };

  let analysis = $state<AnalysisResult | null>(null);
  let history = $state<HistoryPoint[]>([]);
  let consumptionStats = $state<{ mean: number; std: number }>({
    mean: 0,
    std: 0,
  });
  let error = $state<string | null>(null);
  let loading = $state(true);

  let splitEl: HTMLDivElement | null = $state(null);
  let splitChart: echarts.ECharts | null = null;

  function meanStd(values: number[]): { mean: number; std: number } {
    const filtered = values.filter(
      (v) => Number.isFinite(v) && v > 0,
    );
    if (filtered.length === 0) return { mean: 0, std: 0 };
    const mean =
      filtered.reduce((acc, v) => acc + v, 0) / filtered.length;
    if (filtered.length < 2) return { mean, std: 0 };
    const variance =
      filtered.reduce((acc, v) => acc + (v - mean) ** 2, 0) /
      (filtered.length - 1);
    return { mean, std: Math.sqrt(variance) };
  }

  function addDays(iso: string, days: number): string {
    const d = new Date(iso);
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  }

  function buildScenarios(
    a: AnalysisResult,
    currentLitres: number,
  ): Scenario[] {
    const today = new Date().toISOString().slice(0, 10);

    const hddBase = a.estimated_daily_consumption_hdd_l;
    const hwOnly = a.estimated_daily_hot_water_consumption_l;
    const avg = a.avg_daily_consumption_l;

    const winterPerDay =
      hddBase != null && hddBase > 0
        ? hddBase * 1.3
        : avg != null && avg > 0
          ? avg * 1.5
          : 0;
    const mildPerDay = avg != null && avg > 0 ? avg : 0;
    const summerPerDay = hwOnly != null && hwOnly > 0 ? hwOnly : 0;

    const make = (
      label: string,
      perDay: number,
      note?: string,
    ): Scenario => {
      if (!Number.isFinite(perDay) || perDay <= 0 || currentLitres <= 0) {
        return {
          label,
          perDayL: perDay,
          daysRemaining: null,
          emptyDate: null,
          note,
        };
      }
      const days = Math.floor(currentLitres / perDay);
      return {
        label,
        perDayL: perDay,
        daysRemaining: days,
        emptyDate: addDays(today, days),
        note,
      };
    };

    return [
      make(
        "Winter day",
        winterPerDay,
        "HDD-driven · ×1.3 of typical heating day",
      ),
      make("Mild day", mildPerDay, "Recent average daily draw"),
      make("Summer day", summerPerDay, "Hot water only"),
    ];
  }

  function buildSplitOption(a: AnalysisResult): echarts.EChartsOption {
    const heating = Number(a.estimated_daily_heating_consumption_l ?? 0);
    const hw = Number(a.estimated_daily_hot_water_consumption_l ?? 0);
    return {
      animation: false,
      tooltip: {
        trigger: "item",
        valueFormatter: (v: unknown) =>
          typeof v === "number" ? `${v.toFixed(2)} L/day` : "—",
      },
      legend: {
        bottom: 0,
        textStyle: { color: "#94a3b8" },
        icon: "circle",
      },
      series: [
        {
          name: "Daily split",
          type: "pie",
          radius: ["55%", "75%"],
          center: ["50%", "45%"],
          avoidLabelOverlap: true,
          label: {
            show: true,
            color: "#e2e8f0",
            formatter: "{b}\n{d}%",
            fontSize: 11,
          },
          labelLine: { show: true, length: 6, length2: 6 },
          data: [
            {
              name: "Heating",
              value: heating,
              itemStyle: { color: "#3b82f6" },
            },
            {
              name: "Hot water",
              value: hw,
              itemStyle: { color: "#2dd4bf" },
            },
          ],
        },
      ],
    };
  }

  async function loadAll(): Promise<void> {
    try {
      loading = true;
      const [latest, hist, readings] = await Promise.all([
        api.analysisLatest(),
        api.analysisHistory(180),
        api.readings({ limit: 25000, order: "asc" }),
      ]);
      analysis = latest;

      // Keep history compact: last 12 months, one point per day
      // (downsampled to first reading of each calendar day) so the fan
      // chart's run-up isn't drowned out by 17k of sensor broadcasts.
      const cutoff = new Date();
      cutoff.setUTCDate(cutoff.getUTCDate() - 365);
      const cutoffStr = cutoff.toISOString().slice(0, 10);
      const seenDays = new Set<string>();
      const series: HistoryPoint[] = [];
      for (const r of readings.items ?? []) {
        if (r.litres_remaining == null) continue;
        const day = (r.date ?? "").slice(0, 10);
        if (!day || day < cutoffStr) continue;
        if (seenDays.has(day)) continue;
        seenDays.add(day);
        series.push({ date: r.date, litres: Number(r.litres_remaining) });
      }
      history = series;

      const histSorted = [...(hist.items ?? [])].sort((a, b) =>
        (a.latest_reading_date ?? "").localeCompare(
          b.latest_reading_date ?? "",
        ),
      );
      const last30 = histSorted
        .slice(-30)
        .map((it) => Number(it.avg_daily_consumption_l ?? 0))
        .filter((v) => Number.isFinite(v) && v > 0);
      consumptionStats = meanStd(last30);

      // Fallback when history can't seed mean (e.g. fresh install): use the
      // latest analysis figure so the median path still draws.
      if (consumptionStats.mean <= 0 && latest.avg_daily_consumption_l != null) {
        consumptionStats = {
          mean: Number(latest.avg_daily_consumption_l) || 0,
          std: consumptionStats.std,
        };
      }
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  function onResize(): void {
    splitChart?.resize();
  }

  onMount(() => {
    loadAll();
    window.addEventListener("resize", onResize);
  });

  onDestroy(() => {
    window.removeEventListener("resize", onResize);
    splitChart?.dispose();
    splitChart = null;
  });

  $effect(() => {
    if (!splitEl || !analysis) return;
    if (!splitChart) {
      splitChart = echarts.init(splitEl, KEROTRACK_DARK_THEME);
    }
    splitChart.setOption(buildSplitOption(analysis), true);
  });

  let currentLitres = $derived(
    history.length > 0 ? history[history.length - 1].litres : 0,
  );
  let scenarios = $derived(
    analysis ? buildScenarios(analysis, currentLitres) : [],
  );
  // Fan horizon: clip at 365d max, and at the analysis-projected empty date
  // when we have one — projecting past zero just reads as misleading flat
  // bands along the X-axis.
  let fanHorizonDays = $derived(
    Math.max(
      14,
      Math.min(
        365,
        Math.floor(analysis?.estimated_days_remaining ?? 365),
      ),
    ),
  );
</script>

<div class="space-y-6">
  <div>
    <h1 class="text-lg font-semibold">Forecast</h1>
    <p class="text-xs text-text-muted">
      Median run-out projection with p25/p75 (inter-quartile) and p5/p95
      envelopes, scenario comparisons, and the heating vs hot-water split.
    </p>
  </div>

  {#if error}
    <p class="text-xs text-brand-red">{error}</p>
  {:else if loading && !analysis}
    <p class="text-xs text-text-muted">Loading forecast…</p>
  {:else if analysis}
    <section class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatCard
        label="Days remaining"
        value={analysis.estimated_days_remaining != null
          ? analysis.estimated_days_remaining.toFixed(0)
          : "—"}
        unit="days"
      />
      <StatCard
        label="Empty by"
        value={analysis.estimated_empty_date ?? "—"}
      />
      <StatCard
        label="Avg daily L"
        value={analysis.avg_daily_consumption_l != null
          ? analysis.avg_daily_consumption_l.toFixed(2)
          : "—"}
        unit="L/day"
      />
      <StatCard
        label="Heating split"
        value={analysis.estimated_daily_heating_consumption_l != null
          ? analysis.estimated_daily_heating_consumption_l.toFixed(2)
          : "—"}
        unit="L/day"
        sub={`Hot water ${
          analysis.estimated_daily_hot_water_consumption_l != null
            ? analysis.estimated_daily_hot_water_consumption_l.toFixed(2)
            : "—"
        } L/day`}
      />
    </section>

    <section class="space-y-2">
      <div class="flex items-baseline justify-between">
        <h2 class="text-sm font-semibold">Forecast fan</h2>
        <span class="text-[11px] text-text-subtle font-mono">
          μ={consumptionStats.mean.toFixed(2)} L/day · σ={consumptionStats.std.toFixed(
            2,
          )} L/day · {history.length} readings
        </span>
      </div>
      <div class="rounded-lg border border-border bg-bg-panel p-3">
        <ForecastFan
          history={history}
          meanDailyL={consumptionStats.mean}
          stdDailyL={consumptionStats.std}
          horizonDays={fanHorizonDays}
          height="360px"
        />
      </div>
    </section>

    <section class="space-y-2">
      <h2 class="text-sm font-semibold">Scenarios</h2>
      <div class="grid grid-cols-1 gap-3 md:grid-cols-3">
        {#each scenarios as s}
          <div
            class="rounded-lg border border-border bg-bg-panel px-4 py-3"
          >
            <div class="text-[10px] uppercase tracking-wide text-text-label">
              {s.label}
            </div>
            <div class="mt-1 flex items-baseline gap-1">
              <span class="font-mono text-2xl font-semibold text-text">
                {s.daysRemaining != null ? s.daysRemaining : "—"}
              </span>
              <span class="text-xs text-text-muted">days</span>
            </div>
            <div class="mt-1 text-[11px] text-text-subtle">
              {s.perDayL > 0 ? `${s.perDayL.toFixed(2)} L/day` : "no data"}
              {#if s.emptyDate}· empty {s.emptyDate}{/if}
            </div>
            {#if s.note}
              <div class="mt-1 text-[11px] text-text-subtle">{s.note}</div>
            {/if}
          </div>
        {/each}
      </div>
    </section>

    <section class="space-y-2">
      <div class="flex items-baseline justify-between">
        <h2 class="text-sm font-semibold">Heating vs hot water split</h2>
        <span class="text-[11px] text-text-subtle font-mono">
          latest analysis snapshot · {analysis.latest_analysis_date ?? "—"}
        </span>
      </div>
      {#if (analysis.estimated_daily_heating_consumption_l ?? 0) === 0 && (analysis.estimated_daily_hot_water_consumption_l ?? 0) > 0}
        <p class="text-[11px] text-text-subtle">
          Today's HDD is zero — boiler estimated to be on hot water only.
        </p>
      {/if}
      <div class="rounded-lg border border-border bg-bg-panel p-3">
        {#if (analysis.estimated_daily_heating_consumption_l ?? 0) <= 0 && (analysis.estimated_daily_hot_water_consumption_l ?? 0) <= 0}
          <div
            class="flex h-[260px] items-center justify-center text-xs text-text-subtle"
          >
            Heating / hot-water split unavailable
          </div>
        {:else}
          <div bind:this={splitEl} style="width: 100%; height: 260px;"></div>
        {/if}
      </div>
    </section>
  {/if}
</div>
