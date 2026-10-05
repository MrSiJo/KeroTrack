import { describe, expect, it } from "vitest";

import {
  daysUntil,
  fixed,
  scenarioLabel,
  formatAge,
  formatGBP,
  formatPpl,
  latestQuotes,
  priceHistory,
  relativeDays,
  stateLabel,
  stateTone,
  supplierName,
  allInPpl,
} from "$lib/buying";
import type { BuyingQuote } from "$lib/types/api";

const q = (o: Partial<BuyingQuote>): BuyingQuote => ({
  id: 1,
  fetched_at: "2026-10-04 10:00:00",
  supplier: "a",
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

describe("buying helpers", () => {
  it("maps states to tones", () => {
    expect(stateTone("buy_now")).toBe("green");
    expect(stateTone("deadline")).toBe("amber");
    expect(stateTone("overdue")).toBe("red");
    for (const s of ["no_room", "wait", "unknown", "weird", null])
      expect(stateTone(s)).toBe("neutral");
  });

  it("labels states", () => {
    expect(stateLabel("buy_now")).toBe("Buy now");
    expect(stateLabel("nonsense")).toBe("Unknown");
  });

  it("formats money", () => {
    expect(formatPpl(110)).toBe("110.0p");
    expect(formatPpl(null)).toBe("n/a");
    expect(formatGBP(577.71)).toBe("£577.71");
    expect(formatGBP(12)).toBe("£12.00");
  });

  it("counts days across month ends", () => {
    expect(daysUntil("2026-10-10", "2026-10-04")).toBe(6);
    expect(daysUntil("2026-11-02", "2026-10-30")).toBe(3);
    expect(daysUntil("2026-10-01", "2026-10-04")).toBe(-3);
    expect(daysUntil(null, "2026-10-04")).toBeNull();
    expect(daysUntil("bad", "2026-10-04")).toBeNull();
  });

  it("describes relative days", () => {
    expect(relativeDays(0)).toBe("today");
    expect(relativeDays(1)).toBe("in 1 day");
    expect(relativeDays(-3)).toBe("3 days ago");
  });

  it("names suppliers", () => {
    expect(supplierName("homefuelsdirect")).toBe("Home Fuels Direct");
    expect(supplierName("other")).toBe("other");
    expect(supplierName("theheatingoilcompany")).toBe("The Heating Oil Company");
    expect(supplierName("nwffuels")).toBe("NWF Fuels");
    expect(supplierName("westernfuel")).toBe("Western Fuel");
    expect(supplierName("boilerjuice")).toBe("BoilerJuice");
  });

  it("formats age", () => {
    const now = new Date("2026-10-04T12:00:00");
    expect(formatAge("2026-10-04 11:30:00", now)).toBe("30m ago");
    expect(formatAge("2026-10-04 06:00:00", now)).toBe("6h ago");
    expect(formatAge("2026-10-01 12:00:00", now)).toBe("3d ago");
  });

  it("keeps only the latest poll per supplier", () => {
    const rows = [
      q({ id: 1, fetched_at: "2026-10-03 10:00:00" }),
      q({ id: 2, fetched_at: "2026-10-04 10:00:00", urgent: 1 }),
      q({ id: 3, fetched_at: "2026-10-04 10:00:00" }),
      q({ id: 4, kind: "index" }),
    ];
    expect(latestQuotes(rows).map((r) => r.id)).toEqual([3, 2]);
  });

  it("builds price history from index and best non-urgent quotes", () => {
    const rows = [
      q({ kind: "index", fetched_at: "2026-10-02 00:00:00", ppl_effective: 108 }),
      q({ fetched_at: "2026-10-02 01:00:00", ppl_effective: 112 }),
      q({ fetched_at: "2026-10-02 01:00:00", ppl_effective: 110 }),
      q({ fetched_at: "2026-10-02 01:00:00", ppl_effective: 90, urgent: 1 }),
      q({ fetched_at: "2026-10-03 01:00:00", ppl_effective: 95, ok: 0 }),
    ];
    const h = priceHistory(rows);
    // VAT added: the chart shows real prices, like the trigger.
    expect(h.index).toEqual([["2026-10-02 00:00:00", 113.4]]);
    expect(h.best).toEqual([["2026-10-02 01:00:00", 115.5]]);
  });

  it("takes the best quote per day across suppliers polled at different times", () => {
    const rows = [
      q({ id: 1, fetched_at: "2026-10-05 07:00:00", supplier: "hfd", ppl_effective: 110 }),
      q({ id: 2, fetched_at: "2026-10-05 10:30:00", supplier: "wf", ppl_effective: 106 }),
      q({ id: 3, fetched_at: "2026-10-05 13:00:00", supplier: "hfd", ppl_effective: 111 }),
      q({ id: 4, fetched_at: "2026-10-06 07:00:00", supplier: "hfd", ppl_effective: 109 }),
    ];
    const best = priceHistory(rows).best;
    expect(best.map((p) => p[0])).toEqual(["2026-10-05 10:30:00", "2026-10-06 07:00:00"]);
    expect(best[0][1]).toBeCloseTo(111.3, 6); // 106p ex VAT
    expect(best[1][1]).toBeCloseTo(114.45, 6); // 109p ex VAT
  });

  it("prices a litre all in from the total", () => {
    // Western Fuel 2026-10-05: £560.26 for 500 L incl. £12 fee and VAT.
    expect(allInPpl({ total_inc_vat: 560.26, litres: 500 })).toBeCloseTo(112.05, 2);
    expect(allInPpl({ total_inc_vat: null, litres: 500 })).toBeNull();
    expect(allInPpl({ total_inc_vat: 560.26, litres: 0 })).toBeNull();
  });

  it("formats nullable numbers", () => {
    expect(fixed(0.12345, 3)).toBe("0.123");
    expect(fixed(null, 2)).toBe("n/a");
    expect(fixed(undefined, 2)).toBe("n/a");
    expect(fixed(Number.NaN, 2)).toBe("n/a");
  });

  it("labels scenarios", () => {
    expect(scenarioLabel("normal")).toBe("Normal");
    expect(scenarioLabel("mild_then_cold")).toBe("Mild then cold");
    expect(scenarioLabel("cold")).toBe("Cold");
    expect(scenarioLabel("very_wet")).toBe("Very wet");
  });
});
