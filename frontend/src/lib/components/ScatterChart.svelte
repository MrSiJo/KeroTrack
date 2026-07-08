<script lang="ts">
  import type * as echarts from "echarts";

  import { useEchart } from "$lib/charts/echart.svelte";

  type Point = { x: number; y: number };

  type Props = {
    points: Point[];
    xLabel: string;
    yLabel: string;
    height?: string;
  };

  let { points, xLabel, yLabel, height = "320px" }: Props = $props();

  let el: HTMLDivElement | null = $state(null);

  type Regression = {
    slope: number;
    intercept: number;
    r2: number;
    minX: number;
    maxX: number;
  };

  function regress(pts: Point[]): Regression | null {
    const filtered = pts.filter(
      (p) =>
        Number.isFinite(p.x) && Number.isFinite(p.y),
    );
    if (filtered.length < 2) return null;

    const n = filtered.length;
    let sumX = 0;
    let sumY = 0;
    let sumXY = 0;
    let sumXX = 0;
    let minX = Infinity;
    let maxX = -Infinity;

    for (const p of filtered) {
      sumX += p.x;
      sumY += p.y;
      sumXY += p.x * p.y;
      sumXX += p.x * p.x;
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
    }

    const meanX = sumX / n;
    const meanY = sumY / n;
    const denom = sumXX - n * meanX * meanX;
    if (denom === 0) return null;
    const slope = (sumXY - n * meanX * meanY) / denom;
    const intercept = meanY - slope * meanX;

    let ssTot = 0;
    let ssRes = 0;
    for (const p of filtered) {
      const yPred = slope * p.x + intercept;
      ssRes += (p.y - yPred) ** 2;
      ssTot += (p.y - meanY) ** 2;
    }
    const r2 = ssTot === 0 ? 1 : 1 - ssRes / ssTot;

    return { slope, intercept, r2, minX, maxX };
  }

  function buildOption(): echarts.EChartsOption {
    const reg = regress(points);
    const seriesData = points.map((p) => [p.x, p.y]);

    const series: echarts.SeriesOption[] = [
      {
        name: "samples",
        type: "scatter",
        data: seriesData,
        symbolSize: 8,
        itemStyle: { color: "#60a5fa", opacity: 0.75 },
      },
    ];

    const graphic: echarts.EChartsOption["graphic"] = [];

    if (reg) {
      const x0 = reg.minX;
      const x1 = reg.maxX;
      const y0 = reg.slope * x0 + reg.intercept;
      const y1 = reg.slope * x1 + reg.intercept;
      series.push({
        name: "trend",
        type: "line",
        data: [
          [x0, y0],
          [x1, y1],
        ],
        showSymbol: false,
        lineStyle: { color: "#f59e0b", width: 2, type: "dashed" },
        tooltip: { show: false },
        z: 5,
      });

      (graphic as object[]).push({
        type: "text",
        right: 16,
        top: 12,
        style: {
          text: `R² = ${reg.r2.toFixed(3)}\nslope = ${reg.slope.toFixed(3)}`,
          fill: "#94a3b8",
          font: "12px JetBrains Mono, monospace",
        },
      });
    }

    return {
      animation: false,
      tooltip: {
        trigger: "item",
        formatter: (params: unknown) => {
          const p = params as { value?: [number, number]; seriesName?: string };
          if (!p.value) return "";
          const [x, y] = p.value;
          return `${xLabel}: ${x.toFixed(2)}<br/>${yLabel}: ${y.toFixed(2)}`;
        },
      },
      grid: { top: 24, right: 24, bottom: 44, left: 56 },
      xAxis: {
        type: "value",
        name: xLabel,
        nameLocation: "middle",
        nameGap: 28,
        scale: true,
      },
      yAxis: {
        type: "value",
        name: yLabel,
        scale: true,
      },
      series,
      graphic,
    };
  }

  useEchart(
    () => el,
    buildOption,
  );
</script>

{#if !points || points.length === 0}
  <div
    class="flex items-center justify-center rounded border border-border bg-bg-panel text-xs text-text-subtle"
    style="height: {height};"
  >
    No data yet
  </div>
{:else}
  <div bind:this={el} style="width: 100%; height: {height};"></div>
{/if}
