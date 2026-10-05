<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import * as echarts from "echarts";

  import ForecastFan from "$lib/components/ForecastFan.svelte";
  import RunwayChart from "$lib/components/RunwayChart.svelte";
  import StatCard from "$lib/components/StatCard.svelte";
  import { api } from "$lib/api";
  import { daysUntil, fixed, isoToday, relativeDays } from "$lib/buying";
  import { KEROTRACK_DARK_THEME } from "$lib/charts/theme";
  import {
    activeScenario,
    formatDate,
    formatStamp,
    heatingStat,
    scenarioRangeText,
    settingNumber,
  } from "$lib/countdown";
  import { settings } from "$lib/stores/settings";
  import { dailyStats, modelTrend } from "$lib/usageTrend";
  import type { AnalysisResult, BuyingSummary } from "$lib/types/api";

  type HistoryPoint = { date: string; litres: number };

  // Past usage only: the runway is the one projection the app shows.
  const FAN_HORIZON_DAYS = 0;

  let analysis = $state<AnalysisResult | null>(null);
  let summary = $state<BuyingSummary | null>(null);
  let today = $state(isoToday());
  let history = $state<HistoryPoint[]>([]);
  let trend = $state<HistoryPoint[]>([]);
  let consumptionStats = $state<{ mean: number; std: number }>({
    mean: 0,
    std: 0,
  });
  let error = $state<string | null>(null);
  let summaryError = $state<string | null>(null);
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

  function buildSplitOption(a: AnalysisResult): echarts.EChartsOption {
    const heating = Number(a.estimated_daily_heating_consumption_l ?? 0);
    const hw = Number(a.estimated_daily_hot_water_consumption_l ?? 0);
    return {
      animation: false,
      tooltip: {
        trigger: "item",
        // Shares only: the page's one hot water figure is the runway's.
        formatter: "{b}: {d}%",
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
    loading = true;
    // Each fetch stands alone: a failing usage endpoint must not hide the
    // runway, and a failing runway must not hide past usage.
    const [latestR, histR, readingsR, buyingR, hoursR] = await Promise.allSettled([
      api.analysisLatest(),
      api.analysisHistory(180),
      api.readings({ limit: 25000, order: "asc" }),
      api.getBuyingSummary(),
      api.getHeatingHours(400),
    ]);
    today = isoToday();

    if (buyingR.status === "fulfilled") {
      summary = buyingR.value;
      summaryError = null;
    } else {
      summaryError = (buyingR.reason as Error)?.message ?? "unavailable";
    }

    if (latestR.status === "fulfilled") {
      analysis = latestR.value;
      error = null;
    } else {
      error = (latestR.reason as Error)?.message ?? "unavailable";
    }

    if (readingsR.status === "fulfilled") {
      // Keep history compact: last 12 months, one point per day
      // (downsampled to first reading of each calendar day) so the
      // chart isn't drowned out by 17k of sensor broadcasts.
      const cutoff = new Date();
      cutoff.setUTCDate(cutoff.getUTCDate() - 365);
      const cutoffStr = cutoff.toISOString().slice(0, 10);
      const seenDays = new Set<string>();
      const series: HistoryPoint[] = [];
      for (const r of readingsR.value.items ?? []) {
        if (r.litres_remaining == null) continue;
        const day = (r.date ?? "").slice(0, 10);
        if (!day || day < cutoffStr) continue;
        if (seenDays.has(day)) continue;
        seenDays.add(day);
        series.push({ date: r.date, litres: Number(r.litres_remaining) });
      }
      history = series;
      // The trend uses every reading of the day (median), not just the
      // first, so a single ghost echo at midnight cannot steer it. Under
      // the Nest model it follows expected use where the sensor glitches
      // or sticks; otherwise (or without heating hours) the sensor alone.
      const nest = buyingR.status === "fulfilled" && buyingR.value.heating_model === "nest";
      trend = modelTrend(
        dailyStats(
          (readingsR.value.items ?? []).filter(
            (r) => (r.date ?? "").slice(0, 10) >= cutoffStr,
          ),
        ),
        nest && hoursR.status === "fulfilled" ? (hoursR.value.items ?? []) : [],
        Number(summary?.hw_l_per_day ?? Number.NaN),
        Number(summary?.l_per_heating_hour ?? Number.NaN),
      );
    }

    const histItems = histR.status === "fulfilled" ? (histR.value.items ?? []) : [];
    const histSorted = [...histItems].sort((a, b) =>
      (a.latest_reading_date ?? "").localeCompare(b.latest_reading_date ?? ""),
    );
    const last30 = histSorted
      .slice(-30)
      .map((it) => Number(it.avg_daily_consumption_l ?? 0))
      .filter((v) => Number.isFinite(v) && v > 0);
    consumptionStats = meanStd(last30);
    // Fallback when history can't seed the mean (e.g. fresh install).
    if (consumptionStats.mean <= 0 && analysis?.avg_daily_consumption_l != null) {
      consumptionStats = {
        mean: Number(analysis.avg_daily_consumption_l) || 0,
        std: consumptionStats.std,
      };
    }
    loading = false;
  }

  function onResize(): void {
    splitChart?.resize();
  }

  onMount(() => {
    loadAll();
    void settings.refresh();
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

  let scenario = $derived(activeScenario(summary));
  let orderBy = $derived(scenario?.order_by ?? null);
  let runOut = $derived(scenario?.run_out ?? null);
  let range = $derived(scenarioRangeText(summary?.scenarios));
  let heating = $derived(heatingStat(summary));
  let reserve = $derived(settingNumber($settings.items, "projection.reserve_l", 100));
</script>

<div class="space-y-6">
  <div>
    <h1 class="text-lg font-semibold">Usage and runway</h1>
    <p class="text-xs text-text-muted">
      When to order and when the tank reaches its reserve, from the runway
      projection, plus your past usage and the share of heating and hot water.
    </p>
  </div>

  {#if loading && !summary && !analysis}
    <p class="text-xs text-text-muted">Loading forecast...</p>
  {:else}
    <section class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatCard
        label="Order by"
        value={formatDate(orderBy)}
        sub={orderBy ? relativeDays(daysUntil(orderBy, today)) : "No runway yet"}
      />
      <StatCard
        label="Reserve reached"
        value={formatDate(runOut)}
        sub={runOut
          ? `${relativeDays(daysUntil(runOut, today))}, at ${reserve} L`
          : "No runway yet"}
      />
      <StatCard
        label="Hot water"
        value={fixed(summary?.hw_l_per_day, 1)}
        unit="L/day"
      />
      <StatCard
        label={heating.label}
        value={heating.value}
        unit={heating.unit}
        sub={heating.sub}
      />
    </section>

    <section class="space-y-2">
      <h2 class="text-sm font-semibold">Tank runway</h2>
      <div class="rounded-lg border border-border bg-bg-panel p-3">
        {#if summary}
          <RunwayChart scenarios={summary.scenarios} {reserve} />
        {:else}
          <p class="text-xs text-text-subtle">
            Runway unavailable{summaryError ? `: ${summaryError}` : ""}.
          </p>
        {/if}
      </div>
      {#if range}
        <p class="text-xs text-text-muted">{range}</p>
      {/if}
    </section>

    <section class="space-y-2">
      <div class="flex items-baseline justify-between">
        <h2 class="text-sm font-semibold">Past usage</h2>
        <span class="text-[11px] text-text-subtle font-mono">
          {consumptionStats.mean > 0 ? `avg ${consumptionStats.mean.toFixed(2)} L/day · ` : ""}{history.length} readings
        </span>
      </div>
      <p class="text-[11px] text-text-subtle">
        Daily tank level over the last year. The dotted line is the estimated
        real level: it follows the sensor where the sensor is reliable, and
        your expected use (hot water plus Nest heating hours) where the sensor
        glitches or sticks. See the runway above for order and reserve dates.
      </p>
      <div class="rounded-lg border border-border bg-bg-panel p-3">
        <ForecastFan
          history={history}
          {trend}
          meanDailyL={consumptionStats.mean}
          stdDailyL={consumptionStats.std}
          horizonDays={FAN_HORIZON_DAYS}
          height="360px"
        />
      </div>
    </section>

    {#if error}
      <p class="text-xs text-brand-red">Usage analysis unavailable: {error}</p>
    {/if}
    {#if analysis}
    <section class="space-y-2">
      <div class="flex items-baseline justify-between">
        <h2 class="text-sm font-semibold">Heating vs hot water share</h2>
        <span class="text-[11px] text-text-subtle font-mono">
          latest analysis {analysis.latest_analysis_date ? formatStamp(analysis.latest_analysis_date) : "n/a"}
        </span>
      </div>
      {#if (analysis.estimated_daily_heating_consumption_l ?? 0) === 0 && (analysis.estimated_daily_hot_water_consumption_l ?? 0) > 0}
        <p class="text-[11px] text-text-subtle">
          No heating degree days today, so the boiler is estimated to be on hot water only.
        </p>
      {/if}
      <div class="rounded-lg border border-border bg-bg-panel p-3">
        {#if (analysis.estimated_daily_heating_consumption_l ?? 0) <= 0 && (analysis.estimated_daily_hot_water_consumption_l ?? 0) <= 0}
          <div
            class="flex h-[260px] items-center justify-center text-xs text-text-subtle"
          >
            Heating and hot water split unavailable
          </div>
        {:else}
          <div bind:this={splitEl} style="width: 100%; height: 260px;"></div>
        {/if}
      </div>
    </section>
    {/if}
  {/if}
</div>
