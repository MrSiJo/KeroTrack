<script lang="ts">
  import type * as echarts from "echarts";

  import { scenarioLabel } from "$lib/buying";
  import { useEchart } from "$lib/charts/echart.svelte";
  import type { BuyingScenario } from "$lib/types/api";

  type Props = {
    scenarios: Record<string, BuyingScenario>;
    reserve: number;
    height?: string;
  };

  let { scenarios, reserve, height = "320px" }: Props = $props();

  let el: HTMLDivElement | null = $state(null);

  const COLOURS = ["#3b82f6", "#2dd4bf", "#a78bfa", "#f59e0b"];

  let hasData = $derived(
    Object.values(scenarios ?? {}).some((s) => s.series?.length > 0),
  );

  function buildOption(): echarts.EChartsOption {
    const entries = Object.entries(scenarios ?? {});
    const series: echarts.SeriesOption[] = entries.map(([key, sc], i) => {
      const colour = COLOURS[i % COLOURS.length];
      const s: echarts.LineSeriesOption = {
        name: scenarioLabel(key),
        type: "line",
        showSymbol: false,
        data: sc.series.map(([d, l]) => [d, l]),
        lineStyle: { color: colour, width: 2 },
        itemStyle: { color: colour },
      };
      if (i === 0) {
        s.markLine = {
          symbol: "none",
          silent: true,
          data: [
            {
              yAxis: reserve,
              label: { formatter: `Reserve ${reserve} L`, position: "insideEndTop" },
              lineStyle: { color: "#ef4444", type: "dashed" },
            },
          ],
        };
      }
      if (sc.order_by) {
        s.markPoint = {
          symbol: "pin",
          symbolSize: 36,
          itemStyle: { color: colour },
          label: { formatter: "Order", fontSize: 9 },
          data: [
            {
              name: "Order by",
              coord: [sc.order_by, nearest(sc.series, sc.order_by)],
            },
          ],
        };
      }
      return s;
    });
    return {
      animation: false,
      tooltip: { trigger: "axis" },
      legend: { top: 4, right: 12 },
      grid: { top: 40, right: 24, bottom: 36, left: 56 },
      xAxis: { type: "time" },
      yAxis: { type: "value", name: "Litres", min: 0 },
      series,
    };
  }

  function nearest(series: [string, number][], iso: string): number {
    const t = Date.parse(iso);
    let best = series[0]?.[1] ?? 0;
    let bd = Infinity;
    for (const [d, l] of series) {
      const dd = Math.abs(Date.parse(d) - t);
      if (dd < bd) {
        bd = dd;
        best = l;
      }
    }
    return best;
  }

  useEchart(() => el, buildOption);
</script>

{#if !hasData}
  <div
    class="flex items-center justify-center rounded border border-border bg-bg-panel text-xs text-text-subtle"
    style="height: {height};"
  >
    No projection yet
  </div>
{:else}
  <div bind:this={el} style="width: 100%; height: {height};"></div>
{/if}
