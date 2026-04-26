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
