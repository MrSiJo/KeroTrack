<script lang="ts">
  import type * as echarts from "echarts";

  import { useEchart } from "$lib/charts/echart.svelte";

  type Cell = { date: string; value: number };

  type Props = {
    data: Cell[];
    year: number;
    height?: string;
  };

  let { data, year, height = "200px" }: Props = $props();

  let el: HTMLDivElement | null = $state(null);

  function buildOption(): echarts.EChartsOption {
    const cells: [string, number][] = data
      .filter((d) => d && d.date && Number.isFinite(d.value))
      .map((d) => [d.date.slice(0, 10), Number(d.value)]);

    const values = cells.map(([, v]) => v).filter((v) => v > 0);
    const maxV = values.length ? Math.max(...values) : 1;

    return {
      animation: false,
      tooltip: {
        trigger: "item",
        formatter: (params: unknown) => {
          const p = params as { value?: [string, number] };
          if (!p.value) return "";
          const [date, value] = p.value;
          return `${date}<br/>${value.toFixed(2)} L`;
        },
      },
      visualMap: {
        type: "piecewise",
        min: 0,
        max: maxV,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        textStyle: { color: "#94a3b8" },
        pieces: [
          { min: 0, max: maxV * 0.2, color: "#0d9488", label: "low" },
          { min: maxV * 0.2, max: maxV * 0.4, color: "#2dd4bf" },
          { min: maxV * 0.4, max: maxV * 0.6, color: "#fbbf24" },
          { min: maxV * 0.6, max: maxV * 0.8, color: "#f59e0b" },
          { min: maxV * 0.8, color: "#ef4444", label: "high" },
        ],
      },
      calendar: {
        top: 24,
        left: 40,
        right: 16,
        cellSize: ["auto", 14],
        range: String(year),
        itemStyle: {
          color: "transparent",
          borderColor: "#1e293b",
          borderWidth: 1,
        },
        splitLine: { show: false },
        yearLabel: { show: false },
        monthLabel: { color: "#94a3b8", fontSize: 10 },
        dayLabel: { color: "#94a3b8", fontSize: 10, firstDay: 1 },
      },
      series: [
        {
          type: "heatmap",
          coordinateSystem: "calendar",
          data: cells,
        },
      ],
    };
  }

  useEchart(
    () => el,
    buildOption,
  );
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
