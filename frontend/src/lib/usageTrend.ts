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
// `agree` is the share of that day's readings within AGREE_L of its median.
export type DayStat = DayLevel & { agree: number };
export type DayHours = { date: string; hours: number };

type Reading = { date?: string | null; litres_remaining?: number | null };

const DAY_MS = 86_400_000;
// A real delivery is 500 L or more; a ghost echo has been ~170 L.
const REFILL_RISE_L = 300;
const MIN_POINTS = 5;
const AGREE_L = 15;

function median(values: number[]): number {
  const v = [...values].sort((a, b) => a - b);
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

export function dailyStats(readings: Reading[]): DayStat[] {
  const byDay = new Map<string, number[]>();
  for (const r of readings) {
    const day = (r.date ?? "").slice(0, 10);
    const l = r.litres_remaining;
    if (!day || l == null || !Number.isFinite(Number(l))) continue;
    const list = byDay.get(day) ?? [];
    list.push(Number(l));
    byDay.set(day, list);
  }
  return [...byDay.keys()].sort().map((date) => {
    const values = byDay.get(date)!;
    const m = median(values);
    const near = values.filter((v) => Math.abs(v - m) <= AGREE_L).length;
    return { date, litres: m, agree: near / values.length };
  });
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

// Model driven trend: the Nest model gives the shape (expected use per day
// = hot water + litres per heating hour x heating hours), the sensor gives
// the level wherever it can be trusted. See
// docs/superpowers/specs/2026-10-05-usage-trend-nest-model.md.

const TRUST_AGREE = 0.8;
// A trusted day's offset (sensor + cumulative expected use) sits within
// this of the running level; further away is a phantom or an unexplained drop.
const GATE_L = 30;
const GATE_ALPHA = 0.1;
const GATE_SEED_DAYS = 14;
// Stuck sensor: a run of days whose medians stay inside a three step band
// (about 32 L, so flicker between steps stays in) while the model expects
// more than STUCK_ALLOW_L of use. Untrusted days are see through: they
// neither join nor break a run unless their median is in the band.
const STUCK_BAND_L = 32;
const STUCK_ALLOW_L = 45;
const SENSOR_STEP_L = 11;
// Trusted days further apart than this are separate runs for the offset fit.
const GAP_DAYS = 7;

function gatePass(order: number[], r: number[], candidate: boolean[]): boolean[] {
  const pass = r.map(() => false);
  const seed = order.filter((i) => candidate[i]).slice(0, GATE_SEED_DAYS);
  if (seed.length === 0) return pass;
  let level = median(seed.map((i) => r[i]));
  for (const i of order) {
    if (!candidate[i] || Math.abs(r[i] - level) > GATE_L) continue;
    pass[i] = true;
    level += GATE_ALPHA * (r[i] - level);
  }
  return pass;
}

function stuckDays(seg: DayLevel[], cum: number[], trusted: boolean[]): boolean[] {
  const stuck = seg.map(() => false);
  let members: number[] = [];
  let lo = Infinity;
  let hi = -Infinity;
  const close = () => {
    // Only trusted days measure the run: a phantom that happens to land in
    // the band must not stretch it.
    const firstTrusted = members.find((j) => trusted[j]);
    const lastTrusted = [...members].reverse().find((j) => trusted[j]);
    if (firstTrusted === undefined || lastTrusted === undefined) return;
    if (cum[lastTrusted] - cum[firstTrusted] <= STUCK_ALLOW_L) return;
    // The plateau starts where the sensor first landed on its final level.
    const level = seg[lastTrusted].litres;
    const from = members.find((j) => Math.abs(seg[j].litres - level) <= SENSOR_STEP_L)!;
    for (const j of members) if (j >= from) stuck[j] = true;
  };
  seg.forEach((p, i) => {
    const nlo = Math.min(lo, p.litres);
    const nhi = Math.max(hi, p.litres);
    if (nhi - nlo <= STUCK_BAND_L) {
      members.push(i);
      lo = nlo;
      hi = nhi;
    } else if (trusted[i]) {
      close();
      members = [i];
      lo = hi = p.litres;
    }
  });
  close();
  return stuck;
}

function modelSegment(
  seg: DayStat[],
  hoursByDay: Map<string, number>,
  hw: number,
  a: number,
  halfWindowDays: number,
): DayLevel[] {
  const x = seg.map((p) => Date.parse(p.date) / DAY_MS);
  const use = (d: string) => hw + a * Math.max(hoursByDay.get(d) ?? 0, 0);
  const cum: number[] = [0];
  for (let i = 1; i < seg.length; i++) {
    cum.push(cum[i - 1] + use(seg[i].date) * (x[i] - x[i - 1]));
  }
  const r = seg.map((p, i) => p.litres + cum[i]);
  const candidate = seg.map((p) => p.agree >= TRUST_AGREE);
  const idx = seg.map((_, i) => i);
  const fwd = gatePass(idx, r, candidate);
  const bwd = gatePass([...idx].reverse(), r, candidate);
  let trusted = idx.map((i) => candidate[i] && (fwd[i] || bwd[i]));
  const stuck = stuckDays(seg, cum, trusted);
  trusted = trusted.map((t, i) => t && !stuck[i]);

  const keep = idx.filter((i) => trusted[i]);
  if (keep.length < MIN_POINTS) return usageTrend(seg, halfWindowDays);
  // Fit each unbroken run of trusted days on its own: smoothing across an
  // untrusted gap would blend the far side into the near one. The gaps
  // are bridged by the interpolation below instead.
  const offsetAt = new Map<number, number>();
  let block: number[] = [];
  const flush = () => {
    const fit = block.length >= MIN_POINTS
      ? robustFit(block.map((i) => ({ date: seg[i].date, litres: r[i] })), halfWindowDays)
      : block.map(() => median(block.map((i) => r[i])));
    block.forEach((i, k) => offsetAt.set(i, fit[k]));
    block = [];
  };
  for (const i of keep) {
    if (block.length && x[i] - x[block.at(-1)!] > GAP_DAYS) flush();
    block.push(i);
  }
  flush();

  // Between trusted days the offset moves linearly in time, so a gap is
  // spread evenly; before the first or after the last it holds (pure model).
  let prev = -1;
  let next = 0;
  let floor = Infinity;
  return seg.map((p, i) => {
    while (next < keep.length && keep[next] < i) next++;
    if (trusted[i]) prev = i;
    let offset: number;
    if (offsetAt.has(i)) offset = offsetAt.get(i)!;
    else if (prev < 0) offset = offsetAt.get(keep[0])!;
    else if (next >= keep.length) offset = offsetAt.get(prev)!;
    else {
      const q = keep[next];
      const w = (x[i] - x[prev]) / (x[q] - x[prev]);
      offset = offsetAt.get(prev)! * (1 - w) + offsetAt.get(q)! * w;
    }
    floor = Math.min(floor, offset - cum[i]);
    return { date: p.date, litres: Math.round(floor * 10) / 10 };
  });
}

export function modelTrend(
  stats: DayStat[],
  hours: DayHours[],
  hwPerDay: number,
  lPerHeatingHour: number,
  halfWindowDays = 45,
): DayLevel[] {
  const usable =
    stats.length >= MIN_POINTS &&
    hours.length > 0 &&
    Number.isFinite(hwPerDay) &&
    hwPerDay >= 0 &&
    Number.isFinite(lPerHeatingHour) &&
    lPerHeatingHour > 0;
  if (!usable) return usageTrend(stats, halfWindowDays);
  const hoursByDay = new Map(hours.map((h) => [h.date.slice(0, 10), Number(h.hours)]));
  const bounds = [0, ...refillSplits(stats), stats.length];
  const out: DayLevel[] = [];
  for (let s = 0; s + 1 < bounds.length; s++) {
    const seg = stats.slice(bounds[s], bounds[s + 1]);
    out.push(
      ...(seg.length >= MIN_POINTS
        ? modelSegment(seg, hoursByDay, hwPerDay, lPerHeatingHour, halfWindowDays)
        : usageTrend(seg, halfWindowDays)),
    );
  }
  return out;
}
