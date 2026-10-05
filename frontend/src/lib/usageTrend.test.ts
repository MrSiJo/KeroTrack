import { describe, expect, it } from "vitest";

import {
  dailyMedians,
  modelTrend,
  usageTrend,
  type DayHours,
  type DayLevel,
  type DayStat,
} from "./usageTrend";

function day(i: number): string {
  const d = new Date(Date.UTC(2026, 0, 1));
  d.setUTCDate(d.getUTCDate() + i);
  return d.toISOString().slice(0, 10);
}

function line(n: number, start: number, perDay: number): DayLevel[] {
  return Array.from({ length: n }, (_, i) => ({
    date: day(i),
    litres: start - perDay * i,
  }));
}

describe("dailyMedians", () => {
  it("takes the median of each calendar day, sorted by date", () => {
    const out = dailyMedians([
      { date: "2026-01-02T10:00:00", litres_remaining: 500 },
      { date: "2026-01-01T09:00:00", litres_remaining: 600 },
      { date: "2026-01-01T10:00:00", litres_remaining: 0 },
      { date: "2026-01-01T11:00:00", litres_remaining: 590 },
      { date: "2026-01-02T11:00:00", litres_remaining: null },
    ]);
    expect(out).toEqual([
      { date: "2026-01-01", litres: 590 },
      { date: "2026-01-02", litres: 500 },
    ]);
  });
});

describe("usageTrend", () => {
  it("follows a clean decline", () => {
    const pts = line(120, 900, 2);
    const t = usageTrend(pts);
    expect(t).toHaveLength(120);
    for (let i = 0; i < 120; i++) {
      expect(Math.abs(t[i].litres - pts[i].litres)).toBeLessThan(3);
    }
  });

  it("rides through a month of ghost echoes instead of jumping to them", () => {
    const pts = line(150, 600, 1);
    // Days 60 to 89: the sensor locks onto a phantom 170 L too high.
    for (let i = 60; i < 90; i++) pts[i] = { ...pts[i], litres: pts[i].litres + 170 };
    // Scattered low drop-outs.
    pts[30] = { ...pts[30], litres: 0 };
    pts[100] = { ...pts[100], litres: 320 };
    const t = usageTrend(pts);
    for (let i = 0; i < 150; i++) {
      expect(Math.abs(t[i].litres - (600 - i))).toBeLessThan(15);
    }
  });

  it("never rises between refills", () => {
    const pts = line(90, 500, 0.8).map((p, i) => ({
      ...p,
      litres: p.litres + (i % 3 === 0 ? 10 : 0),
    }));
    const t = usageTrend(pts);
    for (let i = 1; i < t.length; i++) {
      expect(t[i].litres).toBeLessThanOrEqual(t[i - 1].litres);
    }
  });

  it("restarts at a refill rather than smoothing across it", () => {
    const pts = [...line(60, 400, 2), ...line(60, 1100, 2).map((p, i) => ({
      date: day(60 + i),
      litres: p.litres,
    }))];
    const t = usageTrend(pts);
    expect(t[59].litres).toBeLessThan(300);
    expect(t[60].litres).toBeGreaterThan(1050);
  });

  it("returns nothing for too little data", () => {
    expect(usageTrend(line(3, 500, 1))).toEqual([]);
  });
});

describe("modelTrend", () => {
  const HW = 0.9;
  function stats(levels: number[], agree: (i: number) => number = () => 1): DayStat[] {
    return levels.map((litres, i) => ({ date: day(i), litres, agree: agree(i) }));
  }
  function hours(n: number, h: (i: number) => number = () => 0): DayHours[] {
    return Array.from({ length: n }, (_, i) => ({ date: day(i), hours: h(i) }));
  }
  const truth = (i: number) => 600 - HW * i;

  it("follows the model while the sensor is stuck", () => {
    const levels = Array.from({ length: 200 }, (_, i) => (i < 100 ? truth(i) : truth(100)));
    const t = modelTrend(stats(levels), hours(200), HW, 0.74);
    expect(Math.abs(t[199].litres - truth(199))).toBeLessThan(8);
    for (let i = 1; i < t.length; i++) expect(t[i].litres).toBeLessThanOrEqual(t[i - 1].litres);
  });

  it("rides the model through a unanimous phantom month and drop outs", () => {
    const levels = Array.from({ length: 150 }, (_, i) => truth(i));
    for (let i = 60; i < 90; i++) levels[i] += 170;
    for (let i = 50; i < 60; i++) levels[i] -= 100;
    const t = modelTrend(stats(levels, (i) => (i >= 50 && i < 60 ? 0.6 : 1)), hours(150), HW, 0.74);
    for (let i = 0; i < 150; i++) expect(Math.abs(t[i].litres - truth(i))).toBeLessThan(10);
  });

  it("follows the sensor when the model runs light in winter", () => {
    // Model expects 0.87 + 0.74 * 6 = 5.31 L/day; the tank really uses 6.
    const levels = Array.from({ length: 150 }, (_, i) => 1000 - 6 * i);
    const t = modelTrend(stats(levels), hours(150, () => 6), 0.87, 0.74);
    for (let i = 0; i < 150; i++) expect(Math.abs(t[i].litres - levels[i])).toBeLessThan(10);
  });

  it("joins the two sides of a glitch without a step", () => {
    const levels = Array.from({ length: 180 }, (_, i) => (i < 90 ? truth(i) : truth(i) - 40));
    for (let i = 60; i < 90; i++) levels[i] = i % 2 ? 330 : 575;
    const t = modelTrend(stats(levels, (i) => (i >= 60 && i < 90 ? 0.5 : 1)), hours(180), HW, 0.74);
    expect(Math.abs(t[55].litres - truth(55))).toBeLessThan(8);
    expect(Math.abs(t[120].litres - (truth(120) - 40))).toBeLessThan(8);
    for (let i = 1; i < t.length; i++) {
      expect(t[i - 1].litres - t[i].litres).toBeLessThan(HW + 40 / 30 + 1);
    }
  });

  it("falls back to the sensor only trend without heating data", () => {
    const levels = Array.from({ length: 60 }, (_, i) => truth(i));
    const s = stats(levels);
    expect(modelTrend(s, [], HW, 0.74)).toEqual(usageTrend(s));
    expect(modelTrend(s, hours(60), HW, Number.NaN)).toEqual(usageTrend(s));
  });
});
