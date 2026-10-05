import { describe, expect, it } from "vitest";

import {
  activeScenario,
  formatDate,
  formatStamp,
  heatingModelLabel,
  heatingStat,
  nestMonthsText,
  formatShortDate,
  groupQuotesBySupplier,
  hasEnoughHistory,
  priceSummary,
  quoteDayCount,
  scenarioRange,
  scenarioRangeText,
  settingNumber,
  stateSentence,
  stateToneClass,
  timelineGeometry,
} from "$lib/countdown";
import type { BuyingQuote, BuyingScenario, BuyingSummary } from "$lib/types/api";

const q = (o: Partial<BuyingQuote>): BuyingQuote => ({
  id: 1,
  fetched_at: "2026-10-04 10:00:00",
  supplier: "homefuelsdirect",
  kind: "quote",
  litres: 500,
  delivery_by: null,
  delivery_label: "Standard",
  urgent: 0,
  ppl_net: 100,
  total_inc_vat: 600,
  fees_inc_vat: 0,
  ppl_effective: 100,
  ok: 1,
  error: null,
  ...o,
});

const sc = (order_by: string | null, run_out: string | null = null): BuyingScenario => ({
  order_by,
  run_out,
  next_order_by: null,
  series: [],
});

const summary = (o: Partial<BuyingSummary> = {}): BuyingSummary => ({
  state: "wait",
  updated_at: null,
  trigger_ppl: 95,
  headroom_l: 800,
  best: {
    supplier: "homefuelsdirect",
    total_inc_vat: 577.71,
    ppl: 115.54,
    ppl_effective: 110,
    delivery_label: "Standard",
    fetched_at: "2026-10-05 08:00:00",
  },
  quotes: [],
  scenarios: { normal: sc("2027-02-15", "2027-03-10") },
  active_scenario: "normal",
  k: 0.2,
  hw_l_per_day: 1.5,
  context: { index_percentile_365d: null, best_change_30d: null, spread_today: null },
  ...o,
});

describe("formatDate", () => {
  it("formats ISO dates as day month year", () => {
    expect(formatDate("2027-02-15")).toBe("15 Feb 2027");
    expect(formatDate("2026-10-05 08:00:00")).toBe("5 Oct 2026");
    expect(formatDate("2026-12-01T00:00:00")).toBe("1 Dec 2026");
  });
  it("returns n/a for missing or bad input", () => {
    expect(formatDate(null)).toBe("n/a");
    expect(formatDate(undefined)).toBe("n/a");
    expect(formatDate("garbage")).toBe("n/a");
    expect(formatDate("2026-13-01")).toBe("n/a");
  });
  it("formats a stamp with its time", () => {
    expect(formatStamp("2026-10-05 08:07:09")).toBe("5 Oct 2026 08:07");
    expect(formatStamp("2026-10-05T18:30:00")).toBe("5 Oct 2026 18:30");
    expect(formatStamp("2026-10-05")).toBe("5 Oct 2026");
    expect(formatStamp(null)).toBe("n/a");
  });
  it("short form drops the year", () => {
    expect(formatShortDate("2027-02-13")).toBe("13 Feb");
    expect(formatShortDate(null)).toBe("n/a");
  });
});

describe("activeScenario", () => {
  it("uses the active scenario, falling back to normal", () => {
    const s = summary({
      scenarios: { normal: sc("2027-02-15"), cold: sc("2027-01-20") },
      active_scenario: "cold",
    });
    expect(activeScenario(s)?.order_by).toBe("2027-01-20");
    expect(activeScenario({ ...s, active_scenario: null })?.order_by).toBe("2027-02-15");
    expect(activeScenario({ ...s, active_scenario: "missing" })?.order_by).toBe("2027-02-15");
    expect(activeScenario(null)).toBeNull();
  });
});

describe("scenarioRange", () => {
  it("returns earliest and latest order by", () => {
    expect(
      scenarioRange({
        normal: sc("2027-02-15"),
        mild_then_cold: sc("2027-02-14"),
        cold: sc("2027-02-13"),
      }),
    ).toEqual({ earliest: "2027-02-13", latest: "2027-02-15" });
  });
  it("skips scenarios without an order by date", () => {
    expect(
      scenarioRange({ a: sc("2027-02-13"), b: sc(null), c: sc("2027-02-15") }),
    ).toEqual({ earliest: "2027-02-13", latest: "2027-02-15" });
    expect(scenarioRange({ a: sc(null), b: sc(null) })).toBeNull();
  });
  it("is null when all equal, only one, or none", () => {
    expect(scenarioRange({ a: sc("2027-02-15"), b: sc("2027-02-15") })).toBeNull();
    expect(scenarioRange({ a: sc("2027-02-15") })).toBeNull();
    expect(scenarioRange({ a: sc(null), b: sc("2027-02-15") })).toBeNull();
    expect(scenarioRange({})).toBeNull();
    expect(scenarioRange(undefined)).toBeNull();
  });
  it("words the range", () => {
    expect(
      scenarioRangeText({ a: sc("2027-02-13"), b: sc("2027-02-15") }),
    ).toBe("Depending on the winter: order between 13 Feb and 15 Feb");
    expect(
      scenarioRangeText({ a: sc("2026-12-20"), b: sc("2027-01-15") }),
    ).toBe("Depending on the winter: order between 20 Dec 2026 and 15 Jan 2027");
    expect(scenarioRangeText({ a: sc("2027-02-13") })).toBeNull();
  });
});

describe("stateSentence", () => {
  const opts = { minOrderL: 500, today: "2026-10-05" };
  it("wait explains the price against the trigger", () => {
    expect(stateSentence("wait", summary(), opts)).toBe(
      "Price 115.5p (Home Fuels Direct, £577.71) is above your 95.0p trigger.",
    );
  });
  it("wait with the price at or below the trigger stays neutral", () => {
    for (const ppl of [95, 94]) {
      const s = summary({ best: { ...summary().best!, ppl } });
      const text = stateSentence("wait", s, opts);
      expect(text).not.toContain("above");
      expect(text).toBe(
        `Price ${ppl.toFixed(1)}p (Home Fuels Direct, £577.71) against your 95.0p trigger.`,
      );
    }
  });
  it("wait without a local quote", () => {
    expect(stateSentence("wait", summary({ best: null }), opts)).toBe(
      "No local quote yet. Your trigger is 95.0p.",
    );
  });
  it("falls back to the ex VAT price with VAT added when ppl is missing", () => {
    const s = summary({ best: { ...summary().best!, ppl: undefined } });
    expect(stateSentence("wait", s, opts)).toContain("Price 115.5p");
  });
  it("buy_now", () => {
    const s = summary({ best: { ...summary().best!, ppl: 94 } });
    expect(stateSentence("buy_now", s, opts)).toBe(
      "Price 94.0p is at or below your 95.0p trigger. A good time to order.",
    );
  });
  it("deadline counts days to order by", () => {
    const s = summary({ scenarios: { normal: sc("2026-10-15") } });
    expect(stateSentence("deadline", s, opts)).toBe("Order within 10 days.");
    const one = summary({ scenarios: { normal: sc("2026-10-06") } });
    expect(stateSentence("deadline", one, opts)).toBe("Order within 1 day.");
    const zero = summary({ scenarios: { normal: sc("2026-10-05") } });
    expect(stateSentence("deadline", zero, opts)).toBe("Order today.");
  });
  it("overdue, no_room, unknown", () => {
    expect(stateSentence("overdue", summary(), opts)).toBe(
      "Past the order by date. Order now.",
    );
    expect(stateSentence("no_room", summary(), opts)).toBe(
      "Not enough room in the tank for a 500 L delivery.",
    );
    expect(stateSentence("unknown", summary(), opts)).toBe("No fresh prices yet.");
    expect(stateSentence("weird", summary(), opts)).toBe("No fresh prices yet.");
  });
  it("no trigger set", () => {
    for (const t of [null, 0]) {
      expect(stateSentence("wait", summary({ trigger_ppl: t }), opts)).toBe(
        "No price trigger set (Settings > buying).",
      );
    }
  });
  it("copy has no em or en dashes", () => {
    for (const st of ["wait", "buy_now", "deadline", "overdue", "no_room", "unknown"])
      expect(stateSentence(st, summary(), opts)).not.toMatch(/[–—]/);
  });
});

describe("stateToneClass", () => {
  it("maps states to the spec colours", () => {
    expect(stateToneClass("buy_now")).toContain("emerald");
    expect(stateToneClass("deadline")).toContain("amber");
    expect(stateToneClass("overdue")).toContain("red");
    expect(stateToneClass("wait")).toContain("blue");
    expect(stateToneClass("no_room")).toContain("text-muted");
    expect(stateToneClass("unknown")).toContain("text-muted");
    expect(stateToneClass(null)).toContain("text-muted");
  });
});

describe("timelineGeometry", () => {
  it("scales order by and run out against the run out", () => {
    const g = timelineGeometry("2026-10-05", "2027-02-15", "2027-03-10");
    expect(g).not.toBeNull();
    expect(g!.totalDays).toBe(156);
    expect(g!.orderPct).toBeCloseTo((133 / 156) * 100, 5);
    expect(g!.runOutPct).toBe(100);
  });
  it("handles a missing run out", () => {
    const g = timelineGeometry("2026-10-05", "2026-10-15", null);
    expect(g!.orderPct).toBe(100);
    expect(g!.runOutPct).toBeNull();
  });
  it("handles a missing order by", () => {
    const g = timelineGeometry("2026-10-05", null, "2026-10-25");
    expect(g!.orderPct).toBeNull();
    expect(g!.runOutPct).toBe(100);
  });
  it("clamps past dates to zero", () => {
    const g = timelineGeometry("2026-10-05", "2026-09-01", "2026-11-04");
    expect(g!.orderPct).toBe(0);
    expect(g!.runOutPct).toBe(100);
    const all = timelineGeometry("2026-10-05", "2026-09-01", "2026-09-10");
    expect(all!.orderPct).toBe(0);
    expect(all!.runOutPct).toBe(0);
    expect(all!.totalDays).toBe(0);
  });
  it("is null with no dates", () => {
    expect(timelineGeometry("2026-10-05", null, null)).toBeNull();
    expect(timelineGeometry("2026-10-05", "bad", undefined)).toBeNull();
  });
});

describe("hasEnoughHistory", () => {
  const days = (n: number, o: Partial<BuyingQuote> = {}) =>
    Array.from({ length: n }, (_, i) =>
      q({ id: i, fetched_at: `2026-09-${String(i + 1).padStart(2, "0")} 08:00:00`, ...o }),
    );
  it("reports the distinct day count", () => {
    expect(quoteDayCount(days(5))).toBe(5);
    expect(quoteDayCount([...days(3), ...days(3)])).toBe(3);
  });
  it("counts distinct quote days", () => {
    expect(hasEnoughHistory(days(13), 14)).toBe(false);
    expect(hasEnoughHistory(days(14), 14)).toBe(true);
  });
  it("ignores repeat polls on the same day, index rows and failures", () => {
    const same = Array.from({ length: 20 }, (_, i) => q({ id: i }));
    expect(hasEnoughHistory(same, 14)).toBe(false);
    expect(hasEnoughHistory(days(20, { kind: "index" }), 14)).toBe(false);
    expect(hasEnoughHistory(days(20, { ok: 0 }), 14)).toBe(false);
    expect(hasEnoughHistory([], 14)).toBe(false);
  });
});

describe("groupQuotesBySupplier", () => {
  it("picks the cheapest non urgent row per supplier as the default", () => {
    const rows = [
      q({ id: 1, urgent: 1, total_inc_vat: 650 }),
      q({ id: 2, total_inc_vat: 600 }),
      q({ id: 3, total_inc_vat: 590, delivery_label: "Economy" }),
      q({ id: 4, supplier: "b", total_inc_vat: 580 }),
      q({ id: 5, supplier: "b", urgent: 1, total_inc_vat: 700 }),
      q({ id: 6, kind: "index" }),
    ];
    const g = groupQuotesBySupplier(rows);
    expect(g.primary.map((r) => r.id)).toEqual([4, 3]);
    expect(g.others.map((r) => r.id).sort()).toEqual([1, 2, 5]);
  });
  it("only uses the latest poll per supplier", () => {
    const rows = [
      q({ id: 1, fetched_at: "2026-10-03 10:00:00", total_inc_vat: 400 }),
      q({ id: 2, fetched_at: "2026-10-04 10:00:00", total_inc_vat: 600 }),
    ];
    const g = groupQuotesBySupplier(rows);
    expect(g.primary.map((r) => r.id)).toEqual([2]);
    expect(g.others).toEqual([]);
  });
  it("falls back to an urgent or failed row when nothing else exists", () => {
    const g = groupQuotesBySupplier([q({ id: 9, urgent: 1 })]);
    expect(g.primary.map((r) => r.id)).toEqual([9]);
    const f = groupQuotesBySupplier([
      q({ id: 1, ok: 0, total_inc_vat: null }),
      q({ id: 2, ok: 1, urgent: 1 }),
    ]);
    expect(f.primary.map((r) => r.id)).toEqual([2]);
  });
});

describe("priceSummary", () => {
  it("summarises latest best, latest index and change since first", () => {
    const rows = [
      q({ kind: "index", supplier: "boilerjuice", fetched_at: "2026-10-01 06:00:00", ppl_effective: 100 }),
      q({ kind: "index", supplier: "index:boilerjuice", fetched_at: "2026-10-04 06:00:00", ppl_effective: 104 }),
      q({ fetched_at: "2026-10-01 08:00:00", ppl_effective: 112 }),
      q({ fetched_at: "2026-10-04 08:00:00", ppl_effective: 110 }),
      q({ fetched_at: "2026-10-04 08:00:00", ppl_effective: 90, urgent: 1 }),
    ];
    // Real prices: ex VAT figures with VAT added.
    expect(priceSummary(rows)).toEqual({
      latestBest: 115.5,
      latestIndex: 109.2,
      firstBest: 117.60000000000001,
      firstDate: "2026-10-01 08:00:00",
      change: -2.1,
    });
  });
  it("copes with no data", () => {
    expect(priceSummary([])).toEqual({
      latestBest: null,
      latestIndex: null,
      firstBest: null,
      firstDate: null,
      change: null,
    });
  });
});

describe("settingNumber", () => {
  const items = [
    { key: "projection.reserve_l", value: 150 },
    { key: "bad", value: "x" },
    { key: "zero", value: 0 },
  ];
  it("reads a positive numeric setting or falls back", () => {
    expect(settingNumber(items, "projection.reserve_l", 100)).toBe(150);
    expect(settingNumber(items, "bad", 100)).toBe(100);
    expect(settingNumber(items, "zero", 100)).toBe(100);
    expect(settingNumber(items, "missing", 500)).toBe(500);
  });
});

describe("heating model", () => {
  it("labels the model", () => {
    expect(heatingModelLabel("nest")).toBe("Nest heating hours");
    expect(heatingModelLabel("hdd")).toBe("Tank temperature degree days");
    expect(heatingModelLabel(null)).toBe("Tank temperature degree days");
    expect(heatingModelLabel(undefined)).toBe("Tank temperature degree days");
  });

  it("shows litres per heating hour under the Nest model", () => {
    expect(
      heatingStat(summary({ heating_model: "nest", l_per_heating_hour: 0.9372 })),
    ).toEqual({
      label: "Heating",
      value: "0.94",
      unit: "L per heating hour",
      sub: "From your Nest heating hours",
    });
    expect(heatingStat(summary({ heating_model: "nest", l_per_heating_hour: null })).value).toBe("n/a");
  });

  it("keeps the heating factor k otherwise", () => {
    for (const s of [summary({ heating_model: "hdd" }), summary(), null]) {
      const st = heatingStat(s);
      expect(st.label).toBe("Heating factor k");
      expect(st.unit).toBe("");
      expect(st.sub).toBe("Litres per heating degree day");
    }
    expect(heatingStat(summary({ heating_model: "hdd", k: 0.2134 })).value).toBe("0.213");
    expect(heatingStat(null).value).toBe("n/a");
  });

  it("words the Nest months", () => {
    expect(nestMonthsText(5, 2)).toBe("5 months used, 2 excluded (sensor blind)");
    expect(nestMonthsText(1, 0)).toBe("1 month used, 0 excluded (sensor blind)");
    expect(nestMonthsText(null, 3)).toBe("n/a months used, 3 excluded (sensor blind)");
    expect(nestMonthsText(4, null)).toBe("4 months used, n/a excluded (sensor blind)");
  });
});
