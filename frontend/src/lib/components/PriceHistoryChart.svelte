<script lang="ts">
  import type * as echarts from "echarts";

  import { priceHistory } from "$lib/buying";
  import { useEchart } from "$lib/charts/echart.svelte";
  import type { BuyingQuote } from "$lib/types/api";

  type Props = {
    quotes: BuyingQuote[];
    trigger: number | null;
    height?: string;
  };

  let { quotes, trigger, height = "300px" }: Props = $props();

  let el: HTMLDivElement | null = $state(null);

  let hist = $derived(priceHistory(quotes));
  let hasData = $derived(hist.index.length > 0 || hist.best.length > 0);

  function buildOption(): echarts.EChartsOption {
    const best: echarts.LineSeriesOption = {
      name: "Best local price",
      type: "line",
      showSymbol: true,
      symbolSize: 5,
      data: hist.best,
      lineStyle: { color: "#2dd4bf", width: 2 },
      itemStyle: { color: "#2dd4bf" },
    };
    if (trigger != null) {
      best.markLine = {
        symbol: "none",
        silent: true,
        data: [
          {
            yAxis: trigger,
            label: { formatter: `Trigger ${trigger.toFixed(1)}p`, position: "insideEndTop" },
            lineStyle: { color: "#f59e0b", type: "dashed" },
          },
        ],
      };
    }
    return {
      animation: false,
      tooltip: { trigger: "axis" },
      legend: { top: 4, right: 12 },
      grid: { top: 40, right: 24, bottom: 36, left: 56 },
      xAxis: { type: "time" },
      yAxis: { type: "value", name: "Pence per litre (inc VAT)", scale: true },
      series: [
        {
          name: "National index",
          type: "line",
          // The index is polled less often than quotes; with few points a
          // bare line can vanish, so draw its symbols.
          showSymbol: hist.index.length < 60,
          symbolSize: 5,
          data: hist.index,
          lineStyle: { color: "#3b82f6", width: 2 },
          itemStyle: { color: "#3b82f6" },
        },
        best,
      ],
    };
  }

  useEchart(() => el, buildOption);
</script>

{#if !hasData}
  <div
    class="flex items-center justify-center rounded border border-border bg-bg-panel text-xs text-text-subtle"
    style="height: {height};"
  >
    No price history yet
  </div>
{:else}
  <div bind:this={el} style="width: 100%; height: {height};"></div>
{/if}
