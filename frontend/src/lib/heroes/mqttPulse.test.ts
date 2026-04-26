import { describe, it, expect } from "vitest";
import { bucketMessagesPerMinute } from "./mqttPulse";

describe("bucketMessagesPerMinute", () => {
  it("returns 60 zero-buckets for an empty list", () => {
    const buckets = bucketMessagesPerMinute([], Date.now());
    expect(buckets).toHaveLength(60);
    expect(buckets.every((b) => b === 0)).toBe(true);
  });

  it("counts one message in the correct bucket", () => {
    const now = Date.UTC(2026, 3, 26, 12, 0, 0);
    const buckets = bucketMessagesPerMinute(
      [now - 30 * 1000], // 30s ago — last bucket
      now,
    );
    expect(buckets[59]).toBe(1);
    expect(buckets.slice(0, 59).every((b) => b === 0)).toBe(true);
  });

  it("ignores messages older than 60 minutes", () => {
    const now = Date.UTC(2026, 3, 26, 12, 0, 0);
    const buckets = bucketMessagesPerMinute([now - 61 * 60 * 1000], now);
    expect(buckets.every((b) => b === 0)).toBe(true);
  });

  it("ignores messages from the future", () => {
    const now = Date.UTC(2026, 3, 26, 12, 0, 0);
    const buckets = bucketMessagesPerMinute([now + 60 * 1000], now);
    expect(buckets.every((b) => b === 0)).toBe(true);
  });

  it("counts multiple messages in the same minute together", () => {
    const now = Date.UTC(2026, 3, 26, 12, 0, 0);
    const buckets = bucketMessagesPerMinute(
      [now - 10 * 1000, now - 20 * 1000, now - 40 * 1000],
      now,
    );
    expect(buckets[59]).toBe(3);
  });
});
