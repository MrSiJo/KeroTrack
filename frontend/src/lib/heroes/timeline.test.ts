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
    const today = new Date();
    const recent = new Date(today.getTime() - 0)
      .toISOString()
      .slice(0, 10);
    const oldest = new Date(today.getTime() - 30 * 24 * 3600 * 1000)
      .toISOString()
      .slice(0, 10);
    const events = buildTimelineEvents(
      [
        { date: `${oldest} 10:00:00` } as any,
        { date: `${recent} 10:00:00` } as any,
      ],
      31,
    );
    expect(events[0].position).toBeGreaterThanOrEqual(0);
    expect(events[0].position).toBeLessThanOrEqual(1);
    expect(events[1].position).toBeCloseTo(1, 1);
  });
});
