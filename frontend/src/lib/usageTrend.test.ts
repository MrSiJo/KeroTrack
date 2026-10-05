import { describe, expect, it } from "vitest";

import { dailyMedians, usageTrend, type DayLevel } from "./usageTrend";

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
