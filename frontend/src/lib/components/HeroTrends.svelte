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
