// Pure helpers for the order countdown: one answer to "when do I order?".
// Everything date related here is derived from the runway in
// GET /api/buying/summary (active scenario, falling back to "normal").

import { daysUntil, fixed, formatGBP, formatPpl, latestQuotes, priceHistory, supplierName } from "$lib/buying";
import type { BuyingQuote, BuyingScenario, BuyingSummary } from "$lib/types/api";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parts(iso: string | null | undefined): [number, number, number] | null {
  if (!iso) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  return [y, mo, d];
}

/** "2027-02-15" (or a datetime) to "15 Feb 2027"; "n/a" when unusable. */
export function formatDate(iso: string | null | undefined): string {
  const p = parts(iso);
  return p ? `${p[2]} ${MONTHS[p[1] - 1]} ${p[0]}` : "n/a";
}

/** "2026-10-05 08:07:09" to "5 Oct 2026 08:07"; a bare date has no time. */
export function formatStamp(stamp: string | null | undefined): string {
  const day = formatDate(stamp);
  if (day === "n/a") return day;
  const t = /^\d{4}-\d{2}-\d{2}[ T](\d{2}):(\d{2})/.exec(stamp ?? "");
  return t ? `${day} ${t[1]}:${t[2]}` : day;
}

/** "2027-02-13" to "13 Feb". */
export function formatShortDate(iso: string | null | undefined): string {
  const p = parts(iso);
  return p ? `${p[2]} ${MONTHS[p[1] - 1]}` : "n/a";
}

/** The scenario the app projects with, falling back to "normal". */
export function activeScenario(summary: BuyingSummary | null | undefined): BuyingScenario | null {
  if (!summary?.scenarios) return null;
  const key = summary.active_scenario ?? "normal";
  return summary.scenarios[key] ?? summary.scenarios.normal ?? null;
}

/** Earliest and latest order by across scenarios (nulls skipped); null when they agree or fewer than two. */
export function scenarioRange(
  scenarios: Record<string, BuyingScenario> | null | undefined,
): { earliest: string; latest: string } | null {
  const dates = Object.values(scenarios ?? {})
    .map((s) => s.order_by)
    .filter((d): d is string => !!d);
  if (dates.length < 2) return null;
  const sorted = dates.slice().sort();
  const earliest = sorted[0];
  const latest = sorted[sorted.length - 1];
  return earliest === latest ? null : { earliest, latest };
}

export function scenarioRangeText(
  scenarios: Record<string, BuyingScenario> | null | undefined,
): string | null {
  const r = scenarioRange(scenarios);
  if (!r) return null;
  const sameYear = r.earliest.slice(0, 4) === r.latest.slice(0, 4);
  const fmt = sameYear ? formatShortDate : formatDate;
  return `Depending on the winter: order between ${fmt(r.earliest)} and ${fmt(r.latest)}`;
}

/** One plain sentence explaining the buying state. */
export function stateSentence(
  state: string | null | undefined,
  summary: BuyingSummary | null | undefined,
  opts: { minOrderL: number; today: string },
): string {
  const trigger = summary?.trigger_ppl ?? null;
  const hasTrigger = typeof trigger === "number" && trigger > 0;
  const best = summary?.best ?? null;
  switch (state) {
    case "buy_now":
      return `Price ${formatPpl(best?.ppl_effective)} is at or below your ${formatPpl(trigger)} trigger. A good time to order.`;
    case "deadline": {
      const n = daysUntil(activeScenario(summary)?.order_by, opts.today);
      if (n === null) return "Order soon.";
      if (n <= 0) return "Order today.";
      return `Order within ${n} ${n === 1 ? "day" : "days"}.`;
    }
    case "overdue":
      return "Past the order by date. Order now.";
    case "no_room":
      return `Not enough room in the tank for a ${opts.minOrderL} L delivery.`;
    case "wait":
      if (!hasTrigger) return "No price trigger set (Settings > buying).";
      if (!best) return `No local quote yet. Your trigger is ${formatPpl(trigger)}.`;
      return best.ppl_effective > (trigger as number)
        ? `Price ${formatPpl(best.ppl_effective)} (${supplierName(best.supplier)}, ${formatGBP(best.total_inc_vat)}) is above your ${formatPpl(trigger)} trigger.`
        : `Price ${formatPpl(best.ppl_effective)} (${supplierName(best.supplier)}, ${formatGBP(best.total_inc_vat)}) against your ${formatPpl(trigger)} trigger.`;
    default:
      return "No fresh prices yet.";
  }
}

/** Border and text classes per state: buy_now green, deadline amber, overdue red, wait blue. */
export function stateToneClass(state: string | null | undefined): string {
  switch (state) {
    case "buy_now":
      return "border-brand-emerald text-brand-emerald";
    case "deadline":
      return "border-brand-amber text-brand-amber";
    case "overdue":
      return "border-brand-red text-brand-red";
    case "wait":
      return "border-brand-blue text-brand-blue";
    default:
      return "border-border text-text-muted";
  }
}

/**
 * Positions (0 to 100) of the order by and run out markers on a bar that
 * starts today and ends at the later of the two. Past dates clamp to 0.
 */
export function timelineGeometry(
  today: string,
  orderBy: string | null | undefined,
  runOut: string | null | undefined,
): { orderPct: number | null; runOutPct: number | null; totalDays: number } | null {
  const dOrder = daysUntil(orderBy, today);
  const dRun = daysUntil(runOut, today);
  if (dOrder === null && dRun === null) return null;
  const total = Math.max(dOrder ?? 0, dRun ?? 0, 0);
  const pct = (d: number | null): number | null => {
    if (d === null) return null;
    if (total <= 0) return 0;
    return Math.min(100, Math.max(0, (d / total) * 100));
  };
  return { orderPct: pct(dOrder), runOutPct: pct(dRun), totalDays: total };
}

/** True once successful quotes exist on at least `minDays` distinct days. */
export function hasEnoughHistory(items: BuyingQuote[], minDays: number): boolean {
  return quoteDayCount(items) >= minDays;
}

/** Distinct days with at least one successful quote. */
export function quoteDayCount(items: BuyingQuote[]): number {
  const days = new Set<string>();
  for (const r of items) {
    if (r.kind === "quote" && r.ok) days.add(r.fetched_at.slice(0, 10));
  }
  return days.size;
}

function cheapest(rows: BuyingQuote[]): BuyingQuote | undefined {
  return rows
    .slice()
    .sort((a, b) => (a.total_inc_vat ?? Infinity) - (b.total_inc_vat ?? Infinity))[0];
}

/**
 * Latest poll per supplier, split into one default row per supplier
 * (cheapest ok non urgent, else cheapest ok, else anything) and the rest.
 */
export function groupQuotesBySupplier(rows: BuyingQuote[]): {
  primary: BuyingQuote[];
  others: BuyingQuote[];
} {
  const latest = latestQuotes(rows);
  const bySupplier = new Map<string, BuyingQuote[]>();
  for (const r of latest) {
    const list = bySupplier.get(r.supplier) ?? [];
    list.push(r);
    bySupplier.set(r.supplier, list);
  }
  const primary: BuyingQuote[] = [];
  const others: BuyingQuote[] = [];
  for (const list of bySupplier.values()) {
    const ok = list.filter((r) => r.ok);
    const pick =
      cheapest(ok.filter((r) => !r.urgent)) ?? cheapest(ok) ?? list[0];
    primary.push(pick);
    for (const r of list) if (r !== pick) others.push(r);
  }
  primary.sort(
    (a, b) => (a.total_inc_vat ?? Infinity) - (b.total_inc_vat ?? Infinity),
  );
  return { primary, others };
}

/** Compact text summary inputs for when the price chart has too few days. */
export function priceSummary(items: BuyingQuote[]): {
  latestBest: number | null;
  latestIndex: number | null;
  firstBest: number | null;
  firstDate: string | null;
  change: number | null;
} {
  const h = priceHistory(items);
  const first = h.best[0] ?? null;
  const last = h.best[h.best.length - 1] ?? null;
  const idx = h.index[h.index.length - 1] ?? null;
  const change =
    first && last ? Math.round((last[1] - first[1]) * 100) / 100 : null;
  return {
    latestBest: last ? last[1] : null,
    latestIndex: idx ? idx[1] : null,
    firstBest: first ? first[1] : null,
    firstDate: first ? first[0] : null,
    change,
  };
}

/** A positive numeric setting by key, or the fallback. */
export function settingNumber(
  items: { key: string; value: unknown }[],
  key: string,
  fallback: number,
): number {
  const item = items.find((i) => i.key === key);
  const v = Number(item?.value);
  return item && Number.isFinite(v) && v > 0 ? v : fallback;
}

/** Human name of the heating model; anything but "nest" is degree days. */
export function heatingModelLabel(model: string | null | undefined): string {
  return model === "nest" ? "Nest heating hours" : "Tank temperature degree days";
}

/** The Forecast page's heating stat card for the model in use. */
export function heatingStat(summary: BuyingSummary | null | undefined): {
  label: string;
  value: string;
  unit: string;
  sub: string;
} {
  if (summary?.heating_model === "nest") {
    return {
      label: "Heating",
      value: fixed(summary.l_per_heating_hour, 2),
      unit: "L per heating hour",
      sub: "From your Nest heating hours",
    };
  }
  return {
    label: "Heating factor k",
    value: fixed(summary?.k, 3),
    unit: "",
    sub: "Litres per heating degree day",
  };
}

/** "5 months used, 2 excluded (sensor blind)". */
export function nestMonthsText(
  used: number | null | undefined,
  excluded: number | null | undefined,
): string {
  const u = typeof used === "number" && Number.isFinite(used) ? String(used) : "n/a";
  const x = typeof excluded === "number" && Number.isFinite(excluded) ? String(excluded) : "n/a";
  return `${u} ${used === 1 ? "month" : "months"} used, ${x} excluded (sensor blind)`;
}
