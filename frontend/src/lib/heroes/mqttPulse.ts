const WINDOW_MIN = 60;

export function bucketMessagesPerMinute(
  timestampsMs: number[],
  nowMs: number,
): number[] {
  const buckets = new Array<number>(WINDOW_MIN).fill(0);
  const start = nowMs - WINDOW_MIN * 60 * 1000;
  for (const t of timestampsMs) {
    if (t < start || t > nowMs) continue;
    const idx = Math.min(
      WINDOW_MIN - 1,
      Math.floor((t - start) / (60 * 1000)),
    );
    buckets[idx] += 1;
  }
  return buckets;
}
