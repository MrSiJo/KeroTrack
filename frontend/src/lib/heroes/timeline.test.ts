import { describe, it, expect } from "vitest";
import { buildTimelineEvents, type TimelineEvent } from "./timeline";

// A date safely inside every window used below — relative so the tests
// don't rot as the wall clock moves past a hardcoded literal.
const recentDate = new Date(Date.now() - 5 * 24 * 3600 * 1000)
  .toISOString()
  .slice(0, 10);

describe("buildTimelineEvents", () => {
  it("returns an empty array for no readings", () => {
    expect(buildTimelineEvents([], 30)).toEqual([]);
  });

  it("classifies a refill reading as a refill event", () => {
    const events = buildTimelineEvents(
      [{ date: `${recentDate} 10:00:00`, refill_detected: "y" } as any],
      30,
    );
    expect(events).toHaveLength(1);
    expect(events[0].kind).toBe("refill");
  });

  it("classifies an anomaly reading as an anomaly event", () => {
    const events = buildTimelineEvents(
      [{ date: `${recentDate} 10:00:00`, anomaly_detected: "y" } as any],
      30,
    );
    expect(events[0].kind).toBe("anomaly");
  });

  it("classifies a normal reading as a normal event", () => {
    const events = buildTimelineEvents(
      [{ date: `${recentDate} 10:00:00` } as any],
      30,
    );
    expect(events[0].kind).toBe("normal");
  });

  it("filters out readings older than the window", () => {
    const today = new Date();
    const old = new Date(today.getTime() - 60 * 24 * 3600 * 1000)
      .toISOString()
      .slice(0, 10);
    const recent = new Date(today.getTime() - 5 * 24 * 3600 * 1000)
      .toISOString()
      .slice(0, 10);
    const events = buildTimelineEvents(
      [
        { date: `${old} 10:00:00` } as any,
        { date: `${recent} 10:00:00` } as any,
      ],
      30,
    );
    expect(events).toHaveLength(1);
  });

  it("computes a 0..1 normalised position within the window", () => {
    // Stamps are built from Date.now() minus fixed offsets (as UTC, which is
    // how buildTimelineEvents parses them), so the test cannot depend on the
    // time of day: a fixed clock time like 10:00 lies in the future before
    // 10:00 UTC and gets dropped.
    const DAY = 24 * 3600 * 1000;
    const stampAgo = (ms: number) =>
      new Date(Date.now() - ms).toISOString().slice(0, 19).replace("T", " ");
    const events = buildTimelineEvents(
      [
        { date: stampAgo(30 * DAY) } as any,
        { date: stampAgo(60 * 1000) } as any,
      ],
      31,
    );
    expect(events).toHaveLength(2);
    expect(events[0].position).toBeGreaterThanOrEqual(0);
    expect(events[0].position).toBeLessThanOrEqual(1);
    expect(events[0].position).toBeCloseTo(1 / 31, 2);
    expect(events[1].position).toBeCloseTo(1, 1);
  });
});
