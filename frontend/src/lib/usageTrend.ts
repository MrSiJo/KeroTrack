// A noise-resistant trend through the daily tank level, for drawing over
// the raw history. The ultrasonic sensor sometimes locks onto a phantom
// echo for weeks or drops out to near zero; the trend is meant to show
// where the oil level really went underneath that.
//
// Method: daily medians, split at refills, then a robust local linear
// fit (tricube weights in time, bisquare weights on residuals seeded
// from a rolling median so a long run of ghost readings cannot capture
// the first pass), then clamped so it never rises between refills.

export type DayLevel = { date: string; litres: number };

type Reading = { date?: string | null; litres_remaining?: number | null };

const DAY_MS = 86_400_000;
// A real delivery is 500 L or more; a ghost echo has been ~170 L.
const REFILL_RISE_L = 300;
const MIN_POINTS = 5;

function median(values: number[]): number {
  const v = [...values].sort((a, b) => a - b);
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

export function dailyMedians(readings: Reading[]): DayLevel[] {
  const byDay = new Map<string, number[]>();
  for (const r of readings) {
    const day = (r.date ?? "").slice(0, 10);
    const l = r.litres_remaining;
    if (!day || l == null || !Number.isFinite(Number(l))) continue;
    const list = byDay.get(day) ?? [];
    list.push(Number(l));
    byDay.set(day, list);
  }
  return [...byDay.keys()]
    .sort()
    .map((date) => ({ date, litres: median(byDay.get(date)!) }));
}

function refillSplits(pts: DayLevel[]): number[] {
  const splits: number[] = [];
  for (let i = 3; i + 3 <= pts.length; i++) {
    const before = median(pts.slice(i - 3, i).map((p) => p.litres));
    const after = median(pts.slice(i, i + 3).map((p) => p.litres));
    if (
      after - before >= REFILL_RISE_L &&
      pts[i].litres - before >= REFILL_RISE_L &&
      splits.at(-1) !== i - 1
    ) {
      splits.push(i);
    }
  }
  return splits;
}

function bisquare(u: number): number {
  return Math.abs(u) >= 1 ? 0 : (1 - u * u) ** 2;
}

function robustFit(pts: DayLevel[], halfWindowDays: number): number[] {
  const x = pts.map((p) => Date.parse(p.date) / DAY_MS);
  const y = pts.map((p) => p.litres);
  const n = y.length;

  const near = (i: number): number[] => {
    const idx: number[] = [];
    for (let j = 0; j < n; j++) {
      if (Math.abs(x[j] - x[i]) < halfWindowDays) idx.push(j);
    }
    return idx;
  };
  const windows = x.map((_, i) => near(i));

  const localLinear = (i: number, robust: number[]): number => {
    let sw = 0, sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (const j of windows[i]) {
      const d = Math.abs(x[j] - x[i]) / halfWindowDays;
      const w = (1 - d ** 3) ** 3 * robust[j];
      if (w <= 0) continue;
      const dx = x[j] - x[i];
      sw += w; sx += w * dx; sy += w * y[j]; sxx += w * dx * dx; sxy += w * dx * y[j];
    }
    if (sw <= 0) return y[i];
    const denom = sw * sxx - sx * sx;
    // Intercept at dx = 0; fall back to the weighted mean when degenerate.
    return Math.abs(denom) < 1e-9 ? sy / sw : (sy * sxx - sx * sxy) / denom;
  };

  // Seed: residuals against a rolling median, which a minority of ghost
  // days cannot drag.
  let fit = windows.map((w) => median(w.map((j) => y[j])));
  for (let iter = 0; iter < 4; iter++) {
    const res = y.map((v, i) => v - fit[i]);
    const scale = Math.max(6 * median(res.map(Math.abs)), 1);
    const robust = res.map((r) => bisquare(r / scale));
    fit = x.map((_, i) => localLinear(i, robust));
  }
  return fit;
}

export function usageTrend(pts: DayLevel[], halfWindowDays = 45): DayLevel[] {
  if (pts.length < MIN_POINTS) return [];
  const bounds = [0, ...refillSplits(pts), pts.length];
  const out: DayLevel[] = [];
  for (let s = 0; s + 1 < bounds.length; s++) {
    const seg = pts.slice(bounds[s], bounds[s + 1]);
    const fit = seg.length >= MIN_POINTS
      ? robustFit(seg, halfWindowDays)
      : seg.map((p) => p.litres);
    let floor = Infinity;
    seg.forEach((p, i) => {
      floor = Math.min(floor, fit[i]);
      out.push({ date: p.date, litres: Math.round(floor * 10) / 10 });
    });
  }
  return out;
}
