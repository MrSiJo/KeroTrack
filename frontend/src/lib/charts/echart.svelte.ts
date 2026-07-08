// Shared ECharts lifecycle for chart components (KERO-L4).
//
// Every chart used to reimplement init / resize-listener / dispose /
// $effect re-render (~25 lines each, and the copies had already started
// to vary). Call `useEchart` once during component setup:
//
//   let el: HTMLDivElement | null = $state(null);
//   useEchart(() => el, buildOption);
//
// Init/dispose follows element presence rather than component mount —
// charts sit behind a `{#if data.length}` placeholder, so the bound
// element can appear after mount (or disappear) as data loads.

import { untrack } from "svelte";
import * as echarts from "echarts";

import { KEROTRACK_DARK_THEME } from "./theme";

export function useEchart(
  getEl: () => HTMLElement | null,
  buildOption: () => echarts.EChartsOption,
): void {
  let chart: echarts.ECharts | null = null;
  const onResize = () => chart?.resize();

  $effect(() => {
    const el = getEl();
    if (!el) return;
    chart = echarts.init(el, KEROTRACK_DARK_THEME);
    // untrack: data changes are handled by the render effect below —
    // they must not re-init the chart instance.
    untrack(() => chart?.setOption(buildOption()));
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart?.dispose();
      chart = null;
    };
  });

  $effect(() => {
    // Reading buildOption() tracks the component's reactive inputs
    // (props/state used inside it) so the chart re-renders on change.
    const option = buildOption();
    if (chart) chart.setOption(option, true);
  });
}
