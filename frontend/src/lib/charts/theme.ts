// kerotrack-dark ECharts theme — registered once at app boot.
// Palette + typography per ADR-0004.

import * as echarts from "echarts";

export const KEROTRACK_DARK_THEME = "kerotrack-dark";

const PALETTE = {
  blue: "#3b82f6",
  blue2: "#60a5fa",
  blue3: "#93c5fd",
  teal: "#2dd4bf",
  amber: "#f59e0b",
  red: "#ef4444",
  emerald: "#10b981",
  violet: "#a78bfa",
  text: "#e2e8f0",
  textMuted: "#94a3b8",
  border: "#1e293b",
  panel: "#0f172a",
};

let registered = false;

export function registerKeroTrackTheme(): void {
  if (registered || typeof window === "undefined") return;
  registered = true;
  echarts.registerTheme(KEROTRACK_DARK_THEME, {
    color: [
      PALETTE.blue,
      PALETTE.teal,
      PALETTE.violet,
      PALETTE.emerald,
      PALETTE.amber,
      PALETTE.red,
    ],
    backgroundColor: "transparent",
    textStyle: {
      fontFamily: "Inter, system-ui, sans-serif",
      color: PALETTE.text,
    },
    title: {
      textStyle: { color: PALETTE.text, fontWeight: 600 },
      subtextStyle: { color: PALETTE.textMuted },
    },
    legend: { textStyle: { color: PALETTE.textMuted } },
    grid: { borderColor: PALETTE.border, top: 32, right: 24, bottom: 36, left: 56 },
    xAxis: {
      axisLine: { lineStyle: { color: PALETTE.border } },
      axisLabel: { color: PALETTE.textMuted, fontFamily: "JetBrains Mono, monospace" },
      splitLine: { lineStyle: { color: PALETTE.border, type: "dashed" } },
    },
    yAxis: {
      axisLine: { lineStyle: { color: PALETTE.border } },
      axisLabel: { color: PALETTE.textMuted, fontFamily: "JetBrains Mono, monospace" },
      splitLine: { lineStyle: { color: PALETTE.border, type: "dashed" } },
    },
    tooltip: {
      backgroundColor: PALETTE.panel,
      borderColor: PALETTE.border,
      textStyle: { color: PALETTE.text, fontFamily: "JetBrains Mono, monospace" },
    },
    line: { itemStyle: { borderWidth: 0 }, lineStyle: { width: 2 } },
    bar: { itemStyle: { borderRadius: [3, 3, 0, 0] } },
  });
}
