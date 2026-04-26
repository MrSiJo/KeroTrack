<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import * as echarts from "echarts";

  import { KEROTRACK_DARK_THEME } from "$lib/charts/theme";

  type Point = { x: string | number; y1: number | null; y2?: number | null };

  type Props = {
    data: Point[];
    y1Label: string;
    y2Label?: string;
    height?: string;
  };

  let { data, y1Label, y2Label, height = "320px" }: Props = $props();

  let el: HTMLDivElement | null = $state(null);
  let chart: echarts.ECharts | null = null;

  function buildOption(): echarts.EChartsOption {
    const xs = data.map((d) => d.x);
    const y1 = data.map((d) => (d.y1 == null ? null : Number(d.y1)));
    const y2 = data.map((d) => (d.y2 == null ? null : Number(d.y2)));
    const hasY2 = y2Label !== undefined;

    return {
      animation: false,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "line" },
      },
      legend: {
        data: hasY2 ? [y1Label, y2Label!] : [y1Label],
        top: 4,
        right: 12,
      },
      grid: { top: 36, right: hasY2 ? 56 : 24, bottom: 36, left: 56 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: xs as (string | number)[],
        axisLabel: {
          hideOverlap: true,
          formatter: (val: string | number) => {
            const s = String(val);
            // YYYY-MM-DD HH:MM:SS → MM-DD
            if (s.length >= 10) return s.slice(5, 10);
            return s;
          },
        },
      },
      yAxis: hasY2
        ? [
            { type: "value", name: y1Label, scale: true },
            { type: "value", name: y2Label!, scale: true },
          ]
        : [{ type: "value", name: y1Label, scale: true }],
      series: hasY2
        ? [
            {
              name: y1Label,
              type: "line",
              data: y1,
              smooth: true,
              showSymbol: false,
              yAxisIndex: 0,
              lineStyle: { color: "#3b82f6", width: 2 },
              itemStyle: { color: "#3b82f6" },
            },
            {
              name: y2Label!,
              type: "line",
              data: y2,
              smooth: true,
              showSymbol: false,
              yAxisIndex: 1,
              lineStyle: { color: "#2dd4bf", width: 2 },
              itemStyle: { color: "#2dd4bf" },
            },
          ]
        : [
            {
              name: y1Label,
              type: "line",
              data: y1,
              smooth: true,
              showSymbol: false,
              lineStyle: { color: "#3b82f6", width: 2 },
              itemStyle: { color: "#3b82f6" },
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
    // Re-render when data or labels change
    void data;
    void y1Label;
    void y2Label;
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
