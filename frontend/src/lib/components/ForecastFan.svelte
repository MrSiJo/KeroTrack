<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import * as echarts from "echarts";

  import { KEROTRACK_DARK_THEME } from "$lib/charts/theme";

  type HistoryPoint = { date: string; litres: number };

  type Props = {
    history: HistoryPoint[];
    meanDailyL: number;
    stdDailyL: number;
    horizonDays?: number;
    height?: string;
    lowOilThresholdL?: number;
  };

  let {
    history,
    meanDailyL,
    stdDailyL,
    horizonDays = 120,
    height = "360px",
    lowOilThresholdL,
  }: Props = $props();

  let el: HTMLDivElement | null = $state(null);
  let chart: echarts.ECharts | null = null;

  // Quantile multipliers (z-scores) for normal distribution.
  const Z_INNER = 0.674; // p25 / p75 (≈ IQR)
  const Z_OUTER = 1.645; // p5 / p95

  function addDays(iso: string, days: number): string {
    const d = new Date(iso);
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  }

  function clampZero(n: number): number {
    return n < 0 ? 0 : n;
  }

  type Forecast = {
    dates: string[];
    median: (number | null)[];
    p25: (number | null)[];
    p75: (number | null)[];
    p5: (number | null)[];
    p95: (number | null)[];
    innerBand: (number | null)[]; // p75 - p25
    outerBandLower: (number | null)[]; // p25 - p5
    outerBandUpper: (number | null)[]; // p95 - p75
    p25Base: (number | null)[]; // baseline for inner band stack (= p25)
    p5Base: (number | null)[]; // baseline for outer-lower stack (= p5)
    p75Base: (number | null)[]; // baseline for outer-upper stack (= p75)
  };

  function buildForecast(): Forecast {
    const startLitres =
      history.length > 0
        ? Number(history[history.length - 1].litres ?? 0)
        : 0;
    const startDateIso =
      history.length > 0
        ? history[history.length - 1].date.slice(0, 10)
        : new Date().toISOString().slice(0, 10);

    const mu = Number.isFinite(meanDailyL) && meanDailyL > 0 ? meanDailyL : 0;
    const sigma =
      Number.isFinite(stdDailyL) && stdDailyL > 0 ? stdDailyL : 0;

    const dates: string[] = [];
    const median: (number | null)[] = [];
    const p25: (number | null)[] = [];
    const p75: (number | null)[] = [];
    const p5: (number | null)[] = [];
    const p95: (number | null)[] = [];

    for (let i = 0; i <= horizonDays; i++) {
      dates.push(addDays(startDateIso, i));
      const med = clampZero(startLitres - mu * i);
      // Variance grows with sqrt(days) under random-walk assumption.
      const spreadInner = Z_INNER * sigma * Math.sqrt(i);
      const spreadOuter = Z_OUTER * sigma * Math.sqrt(i);

      median.push(med);
      const lo25 = clampZero(med - spreadInner);
      const hi75 = Math.max(lo25, clampZero(med + spreadInner));
      const lo5 = clampZero(med - spreadOuter);
      const hi95 = Math.max(lo5, clampZero(med + spreadOuter));
      p25.push(lo25);
      p75.push(hi75);
      p5.push(lo5);
      p95.push(hi95);
    }

    const innerBand = p25.map((lo, i) => {
      const hi = p75[i] ?? 0;
      return Math.max(0, (hi ?? 0) - (lo ?? 0));
    });
    const outerBandLower = p5.map((lo, i) => {
      const hi = p25[i] ?? 0;
      return Math.max(0, (hi ?? 0) - (lo ?? 0));
    });
    const outerBandUpper = p75.map((lo, i) => {
      const hi = p95[i] ?? 0;
      return Math.max(0, (hi ?? 0) - (lo ?? 0));
    });

    return {
      dates,
      median,
      p25,
      p75,
      p5,
      p95,
      innerBand,
      outerBandLower,
      outerBandUpper,
      p25Base: p25,
      p5Base: p5,
      p75Base: p75,
    };
  }

  function buildHistorySeries(dates: string[]): {
    historyDates: string[];
    historyValues: (number | null)[];
  } {
    if (history.length === 0)
      return { historyDates: [], historyValues: [] };
    // We render history as its own line series with its own x values.
    return {
      historyDates: history.map((h) => h.date.slice(0, 10)),
      historyValues: history.map((h) =>
        h.litres == null ? null : Number(h.litres),
      ),
    };
  }

  function buildOption(): echarts.EChartsOption {
    const f = buildForecast();
    const { historyDates, historyValues } = buildHistorySeries(f.dates);

    const sigma =
      Number.isFinite(stdDailyL) && stdDailyL > 0 ? stdDailyL : 0;
    const drawFan = sigma > 0;

    const pairs = (
      values: (number | null)[],
    ): [string, number | null][] =>
      f.dates.map((d, i) => [d, values[i] ?? null]);

    const fanSeries: echarts.SeriesOption[] = drawFan
      ? [
          // Outer envelope (p5 → p25): transparent base + filled band
          {
            name: "p5-base",
            type: "line",
            stack: "outer-lower",
            data: pairs(f.p5Base),
            symbol: "none",
            lineStyle: { opacity: 0 },
            itemStyle: { opacity: 0 },
            areaStyle: { opacity: 0 },
            silent: true,
            tooltip: { show: false },
            z: 1,
          },
          {
            name: "p5-p25",
            type: "line",
            stack: "outer-lower",
            data: pairs(f.outerBandLower),
            symbol: "none",
            lineStyle: { opacity: 0 },
            areaStyle: { color: "#60a5fa", opacity: 0.2 },
            silent: true,
            tooltip: { show: false },
            z: 1,
          },
          // Outer envelope (p75 → p95)
          {
            name: "p75-base",
            type: "line",
            stack: "outer-upper",
            data: pairs(f.p75Base),
            symbol: "none",
            lineStyle: { opacity: 0 },
            itemStyle: { opacity: 0 },
            areaStyle: { opacity: 0 },
            silent: true,
            tooltip: { show: false },
            z: 1,
          },
          {
            name: "p75-p95",
            type: "line",
            stack: "outer-upper",
            data: pairs(f.outerBandUpper),
            symbol: "none",
            lineStyle: { opacity: 0 },
            areaStyle: { color: "#60a5fa", opacity: 0.2 },
            silent: true,
            tooltip: { show: false },
            z: 1,
          },
          // Inner envelope (p25 → p75)
          {
            name: "p25-base",
            type: "line",
            stack: "inner",
            data: pairs(f.p25Base),
            symbol: "none",
            lineStyle: { opacity: 0 },
            itemStyle: { opacity: 0 },
            areaStyle: { opacity: 0 },
            silent: true,
            tooltip: { show: false },
            z: 2,
          },
          {
            name: "p25-p75 (IQR)",
            type: "line",
            stack: "inner",
            data: pairs(f.innerBand),
            symbol: "none",
            lineStyle: { opacity: 0 },
            areaStyle: { color: "#60a5fa", opacity: 0.4 },
            silent: true,
            tooltip: { show: false },
            z: 2,
          },
        ]
      : [];

    const medianSeries: echarts.SeriesOption = {
      name: "Forecast (median)",
      type: "line",
      data: pairs(f.median),
      symbol: "none",
      smooth: false,
      lineStyle: { color: "#3b82f6", width: 2 },
      itemStyle: { color: "#3b82f6" },
      z: 5,
      markLine: lowOilThresholdL
        ? {
            silent: true,
            symbol: "none",
            lineStyle: { color: "#f59e0b", type: "dashed", width: 1 },
            label: {
              formatter: `Low oil (${lowOilThresholdL} L)`,
              color: "#f59e0b",
              fontSize: 10,
            },
            data: [{ yAxis: lowOilThresholdL }],
          }
        : undefined,
    };

    const series: echarts.SeriesOption[] = [...fanSeries, medianSeries];

    if (historyDates.length > 0) {
      series.push({
        name: "History",
        type: "line",
        data: historyDates.map(
          (d, i) => [d, historyValues[i]] as [string, number | null],
        ),
        symbol: "none",
        smooth: false,
        lineStyle: { color: "#94a3b8", width: 1.5, type: "solid" },
        itemStyle: { color: "#94a3b8" },
        z: 4,
      });
    }

    return {
      animation: false,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "line" },
        valueFormatter: (v: unknown) =>
          typeof v === "number" ? `${v.toFixed(0)} L` : "—",
      },
      legend: {
        data: drawFan
          ? ["Forecast (median)", "p25-p75 (IQR)", "p5-p25", "History"]
          : ["Forecast (median)", "History"],
        top: 4,
        right: 12,
        textStyle: { color: "#94a3b8" },
        selectedMode: false,
      },
      grid: { top: 36, right: 24, bottom: 36, left: 56 },
      xAxis: {
        type: "time",
        axisLabel: {
          hideOverlap: true,
          formatter: (val: number) => {
            const d = new Date(val);
            const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
            const dd = String(d.getUTCDate()).padStart(2, "0");
            return `${mm}-${dd}`;
          },
        },
      },
      yAxis: {
        type: "value",
        name: "Litres",
        scale: true,
        min: 0,
      },
      series,
    };
  }

  function onResize(): void {
    chart?.resize();
  }

  onMount(() => {
    if (!el) return;
    chart = echarts.init(el, KEROTRACK_DARK_THEME);
    chart.setOption(buildOption());
    window.addEventListener("resize", onResize);
  });

  onDestroy(() => {
    window.removeEventListener("resize", onResize);
    chart?.dispose();
    chart = null;
  });

  $effect(() => {
    // Re-render on prop change.
    void history;
    void meanDailyL;
    void stdDailyL;
    void horizonDays;
    void lowOilThresholdL;
    if (chart) chart.setOption(buildOption(), true);
  });
</script>

{#if !history || history.length === 0 || !Number.isFinite(meanDailyL) || meanDailyL <= 0}
  <div
    class="flex items-center justify-center rounded border border-border bg-bg-panel text-xs text-text-subtle"
    style="height: {height};"
  >
    Not enough history to build a forecast yet
  </div>
{:else}
  <div bind:this={el} style="width: 100%; height: {height};"></div>
{/if}
