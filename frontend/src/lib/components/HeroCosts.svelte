<script lang="ts">
  import { onMount } from "svelte";
  import * as echarts from "echarts";
  import HeroShell from "$lib/components/HeroShell.svelte";
  import { KEROTRACK_DARK_THEME } from "$lib/charts/theme";
  import { api } from "$lib/api";

  type Props = { size: "tile" | "full" };
  let { size }: Props = $props();

  type Period = { period: string; cost?: number; total_cost?: number };

  let chartEl = $state<HTMLDivElement | null>(null);
  let chart: echarts.ECharts | null = null;
  let periods = $state<Period[]>([]);

  let last12 = $derived(periods.slice(-12));
  let thisMonth = $derived(last12[last12.length - 1] ?? null);
  let prevMonth = $derived(last12[last12.length - 2] ?? null);
  let thisCost = $derived<number | null>(
    thisMonth ? Number(thisMonth.cost ?? thisMonth.total_cost ?? null) : null,
  );
  let prevCost = $derived<number | null>(
    prevMonth ? Number(prevMonth.cost ?? prevMonth.total_cost ?? null) : null,
  );
  let delta = $derived(
    thisCost != null && prevCost != null ? thisCost - prevCost : null,
  );

  onMount(async () => {
    try {
      const resp = await api.costPeriods();
      periods = (resp.items ?? []) as unknown as Period[];
    } catch {
      periods = [];
    }
  });

  $effect(() => {
    if (!chartEl || last12.length === 0) return;
    chart ??= echarts.init(chartEl, KEROTRACK_DARK_THEME, { renderer: "svg" });
    const data = last12.map((p, i) => ({
      value: Number(p.cost ?? p.total_cost ?? 0),
      itemStyle: {
        color: i === last12.length - 1 ? "#f59e0b" : "#3b82f6",
      },
    }));
    chart.setOption({
      grid: { left: 0, right: 0, top: 4, bottom: 0 },
      xAxis: {
        type: "category",
        show: false,
        data: last12.map((p) => p.period),
      },
      yAxis: { type: "value", show: false },
      series: [
        {
          type: "bar",
          data,
          barCategoryGap: "30%",
        },
      ],
    });
  });

  function fmtMoney(v: number | null): string {
    if (v == null || !Number.isFinite(v)) return "—";
    return `£${Math.round(v)}`;
  }
  function fmtDelta(v: number | null): string {
    if (v == null || !Number.isFinite(v)) return "";
    const arrow = v >= 0 ? "▲" : "▼";
    const colour = v >= 0 ? "amber" : "emerald";
    return `${arrow} £${Math.abs(Math.round(v))}|${colour}`;
  }

  let deltaText = $derived(fmtDelta(delta));
  let deltaLabel = $derived(deltaText.split("|")[0] ?? "");
</script>

<HeroShell
  {size}
  accent="amber"
  label="Costs"
  range="12mo"
  headline={`${fmtMoney(thisCost)} ${deltaLabel}`}
  sub={prevMonth ? `vs ${fmtMoney(prevCost)} last month` : ""}
  href="/costs"
>
  <div bind:this={chartEl} class={size === "tile" ? "h-[34px] w-full" : "h-[100px] w-full"}></div>
</HeroShell>
