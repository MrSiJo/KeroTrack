<script lang="ts">
  import { onMount } from "svelte";
  import * as echarts from "echarts";
  import HeroShell from "$lib/components/HeroShell.svelte";
  import { api } from "$lib/api";
  import { daysUntil, isoToday, relativeDays } from "$lib/buying";
  import { KEROTRACK_DARK_THEME } from "$lib/charts/theme";
  import { activeScenario, formatDate } from "$lib/countdown";
  import type { BuyingSummary } from "$lib/types/api";

  type Props = {
    size: "tile" | "full";
    /** The parent's runway summary; when left out the tile loads its own. */
    summary?: BuyingSummary | null;
  };
  let { size, summary: given = undefined }: Props = $props();

  let chartEl = $state<HTMLDivElement | null>(null);
  let chart: echarts.ECharts | null = null;

  let own = $state<BuyingSummary | null>(null);
  let today = $state(isoToday());

  onMount(async () => {
    today = isoToday();
    if (given !== undefined) return;
    try {
      own = await api.getBuyingSummary();
    } catch {
      own = null;
    }
  });

  let summary = $derived(given !== undefined ? given : own);

  // Order by and the sparkline both come from the runway (active scenario).
  let scenario = $derived(activeScenario(summary));
  let orderBy = $derived(scenario?.order_by ?? null);
  let days = $derived(daysUntil(orderBy, today));

  $effect(() => {
    if (!chartEl) return;
    const series = scenario?.series ?? [];
    if (series.length === 0) return;
    chart ??= echarts.init(chartEl, KEROTRACK_DARK_THEME, { renderer: "svg" });
    chart.setOption({
      grid: { left: 0, right: 0, top: 4, bottom: 0 },
      xAxis: { type: "time", show: false },
      yAxis: { type: "value", show: false, min: 0 },
      series: [
        {
          type: "line",
          data: series.map(([d, l]) => [d, l]),
          showSymbol: false,
          lineStyle: { color: "#a78bfa", width: 1.5 },
          areaStyle: { color: "rgba(167,139,250,0.12)" },
        },
      ],
    });
  });
</script>

<HeroShell
  {size}
  accent="violet"
  label="Forecast"
  range={days != null ? `${days}d` : ""}
  headline={orderBy ? `Order by ${formatDate(orderBy)}` : "Order by n/a"}
  sub={days != null ? relativeDays(days) : ""}
  href="/forecast"
>
  <div bind:this={chartEl} class={size === "tile" ? "h-[34px] w-full" : "h-[100px] w-full"}></div>
</HeroShell>
