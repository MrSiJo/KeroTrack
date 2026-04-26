import type { Reading } from "$lib/types/api";

export type TimelineEvent = {
  kind: "refill" | "anomaly" | "normal";
  position: number; // 0..1 within the window
  date: string;
};

export function buildTimelineEvents(
  readings: Reading[],
  windowDays: number,
): TimelineEvent[] {
  const now = Date.now();
  const windowMs = windowDays * 24 * 3600 * 1000;
  const start = now - windowMs;
  const out: TimelineEvent[] = [];
  for (const r of readings) {
    const ts = Date.parse(r.date.replace(" ", "T") + "Z");
    if (!Number.isFinite(ts) || ts < start || ts > now) continue;
    const kind: TimelineEvent["kind"] =
      r.refill_detected === "y"
        ? "refill"
        : (r as { anomaly_detected?: string }).anomaly_detected === "y"
          ? "anomaly"
          : "normal";
    const position = Math.max(0, Math.min(1, (ts - start) / windowMs));
    out.push({ kind, position, date: r.date });
  }
  return out;
}
