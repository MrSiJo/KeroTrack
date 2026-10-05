// Pure helpers for the buy planner UI.

import type { BuyingQuote, BuyingState } from "$lib/types/api";

export type Tone = "green" | "amber" | "red" | "neutral";

const LABELS: Record<BuyingState, string> = {
  buy_now: "Buy now",
  deadline: "Order soon",
  overdue: "Overdue",
  no_room: "No room for a delivery",
  wait: "Wait",
  unknown: "Unknown",
};

export function stateLabel(state: string | null | undefined): string {
  if (state && state in LABELS) return LABELS[state as BuyingState];
  return LABELS.unknown;
}

export function stateTone(state: string | null | undefined): Tone {
  switch (state) {
    case "buy_now":
      return "green";
    case "deadline":
      return "amber";
    case "overdue":
      return "red";
    default:
      return "neutral";
  }
}

export function formatPpl(n: number | null | undefined): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return "n/a";
  return `${n.toFixed(1)}p`;
}

export function formatGBP(n: number | null | undefined): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return "n/a";
  return `£${n.toFixed(2)}`;
}

function parseDay(iso: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return null;
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

/** Whole calendar days from `today` to `iso` (negative when past). */
export function daysUntil(
  iso: string | null | undefined,
  today: string,
): number | null {
  if (!iso) return null;
  const a = parseDay(iso);
  const b = parseDay(today);
  if (a === null || b === null) return null;
  return Math.round((a - b) / 86_400_000);
}

const SUPPLIERS: Record<string, string> = {
  homefuelsdirect: "Home Fuels Direct",
  theheatingoilcompany: "The Heating Oil Company",
  nwffuels: "NWF Fuels",
  westernfuel: "Western Fuel",
  boilerjuice: "BoilerJuice",
};

export function supplierName(key: string): string {
  return SUPPLIERS[key] ?? key;
}

/**
 * What a litre really costs at checkout: the all in total (VAT, delivery
 * and service fees included) over the litres quoted, in pence.
 */
export function allInPpl(q: Pick<BuyingQuote, "total_inc_vat" | "litres">): number | null {
  if (q.total_inc_vat == null || !q.litres) return null;
  return (q.total_inc_vat / q.litres) * 100;
}

/** Local `YYYY-MM-DD` for a Date. */
export function isoToday(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** "in 5 days", "today", "3 days ago". */
export function relativeDays(days: number | null): string {
  if (days === null) return "n/a";
  if (days === 0) return "today";
  const n = Math.abs(days);
  const unit = n === 1 ? "day" : "days";
  return days > 0 ? `in ${n} ${unit}` : `${n} ${unit} ago`;
}

/** Age of a local naive "YYYY-MM-DD HH:MM:SS" stamp, e.g. "3h ago". */
export function formatAge(stamp: string | null | undefined, now: Date): string {
  if (!stamp) return "n/a";
  const t = new Date(stamp.replace(" ", "T"));
  if (Number.isNaN(t.getTime())) return "n/a";
  const mins = Math.max(0, Math.round((now.getTime() - t.getTime()) / 60_000));
  if (mins < 60) return `${mins}m ago`;
  const h = Math.floor(mins / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

/** Latest poll per supplier + delivery label, newest fetch only. */
export function latestQuotes(quotes: BuyingQuote[]): BuyingQuote[] {
  const quoteRows = quotes.filter((q) => q.kind === "quote");
  const latestBySupplier = new Map<string, string>();
  for (const q of quoteRows) {
    const cur = latestBySupplier.get(q.supplier);
    if (!cur || q.fetched_at > cur) latestBySupplier.set(q.supplier, q.fetched_at);
  }
  return quoteRows
    .filter((q) => q.fetched_at === latestBySupplier.get(q.supplier))
    .sort(
      (a, b) =>
        a.urgent - b.urgent ||
        (a.total_inc_vat ?? Infinity) - (b.total_inc_vat ?? Infinity),
    );
}

/**
 * Index line and best non-urgent ok quote per day, for the price chart.
 *
 * Suppliers poll at different times of day, so one fetch holds only some of
 * them; the daily best compares them all. Each point sits at the fetch time
 * of that day's winning quote.
 */
export function priceHistory(quotes: BuyingQuote[]): {
  index: [string, number][];
  best: [string, number][];
} {
  const index: [string, number][] = [];
  const bestByDay = new Map<string, [string, number]>();
  for (const q of quotes) {
    if (q.ppl_effective == null) continue;
    if (q.kind === "index") {
      index.push([q.fetched_at, q.ppl_effective]);
    } else if (q.kind === "quote" && !q.urgent && q.ok) {
      const day = q.fetched_at.slice(0, 10);
      const cur = bestByDay.get(day);
      if (cur === undefined || q.ppl_effective < cur[1])
        bestByDay.set(day, [q.fetched_at, q.ppl_effective]);
    }
  }
  index.sort((a, b) => a[0].localeCompare(b[0]));
  const best = [...bestByDay.values()].sort((a, b) => a[0].localeCompare(b[0]));
  return { index, best };
}

/** Fixed decimals, or "n/a" for null / non finite. */
export function fixed(n: number | null | undefined, digits: number): string {
  return typeof n === "number" && Number.isFinite(n) ? n.toFixed(digits) : "n/a";
}

const SCENARIO_LABELS: Record<string, string> = {
  normal: "Normal",
  mild_then_cold: "Mild then cold",
  cold: "Cold",
};

export function scenarioLabel(key: string): string {
  if (key in SCENARIO_LABELS) return SCENARIO_LABELS[key];
  const words = key.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
