<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import * as echarts from "echarts";

  import { KEROTRACK_DARK_THEME } from "$lib/charts/theme";

  type Bar = { x: string | number; y: number; anomaly?: boolean };

  type Props = {
    data: Bar[];
    yLabel: string;
    height?: string;
  };

  let { data, yLabel, height = "320px" }: Props = $props();

  let el: HTMLDivElement | null = $state(null);
  let chart: echarts.ECharts | null = null;

  const COLOR_NORMAL = "#3b82f6";
  const COLOR_ANOMALY = "#f59e0b";

  function buildOption(): echarts.EChartsOption {
    const xs = data.map((d) => d.x);
    const series = data.map((d) => ({
      value: Number(d.y) || 0,
      itemStyle: {
        color: d.anomaly ? COLOR_ANOMALY : COLOR_NORMAL,
      },
    }));

    return {
      animation: false,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        valueFormatter: (val: unknown) =>
          typeof val === "number" ? `${val.toFixed(2)} L` : String(val ?? "—"),
      },
      grid: { top: 16, right: 24, bottom: 36, left: 56 },
      xAxis: {
        type: "category",
        data: xs as (string | number)[],
        axisLabel: {
          hideOverlap: true,
          formatter: (val: string | number) => {
            const s = String(val);
            if (s.length >= 10) return s.slice(5, 10);
            return s;
          },
        },
      },
      yAxis: { type: "value", name: yLabel, scale: false },
      series: [
        {
          type: "bar",
          data: series,
          barMaxWidth: 24,
        },
      ],
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
    void data;
    void yLabel;
    if (chart) chart.setOption(buildOption(), true);
  });
</script>

{#if !data || data.length === 0}
  <div
    class="flex items-center justify-center rounded border border-border bg-bg-panel text-xs text-text-subtle"
    style="height: {height};"
  >
    No data yet
  </div>
{:else}
  <div bind:this={el} style="width: 100%; height: {height};"></div>
{/if}
