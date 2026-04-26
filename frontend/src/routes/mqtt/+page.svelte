<script lang="ts">
  import { onDestroy, onMount } from "svelte";

  import { api } from "$lib/api";
  import MqttFeed from "$lib/components/MqttFeed.svelte";

  type FeedItem = { topic: string; payload: unknown; ts: number };
  type LiveState = "connecting" | "open" | "error";

  const MAX_ITEMS = 200;

  let items = $state<FeedItem[]>([]);
  let liveState = $state<LiveState>("connecting");
  let flashKey = $state(0);

  let source: EventSource | null = null;

  function pushItem(item: FeedItem): void {
    const next = [item, ...items];
    if (next.length > MAX_ITEMS) {
      next.length = MAX_ITEMS;
    }
    items = next;
    flashKey += 1;
  }

  function nowTs(): number {
    return Math.floor(Date.now() / 1000);
  }

  function safeParse(raw: string): unknown {
    try {
      return JSON.parse(raw);
    } catch {
      return raw;
    }
  }

  function handleMqttMessage(ev: MessageEvent): void {
    const parsed = safeParse(ev.data);
    let topic = "(unknown)";
    let payload: unknown = parsed;
    if (parsed && typeof parsed === "object") {
      const obj = parsed as Record<string, unknown>;
      if (typeof obj.topic === "string") {
        topic = obj.topic;
      }
      if ("payload" in obj) {
        payload = obj.payload;
      }
    }
    const ts =
      parsed && typeof parsed === "object" && typeof (parsed as { ts?: unknown }).ts === "number"
        ? (parsed as { ts: number }).ts
        : nowTs();
    pushItem({ topic, payload, ts });
  }

  function handleReading(ev: MessageEvent): void {
    const parsed = safeParse(ev.data);
    pushItem({ topic: "oiltank/level", payload: parsed, ts: nowTs() });
  }

  function openStream(): void {
    if (typeof window === "undefined") return;
    if (source) return;
    liveState = "connecting";
    source = new EventSource("/api/stream", { withCredentials: true });
    source.addEventListener("open", () => {
      liveState = "open";
    });
    source.addEventListener("mqtt_message", handleMqttMessage as EventListener);
    source.addEventListener("reading", handleReading as EventListener);
    source.onerror = () => {
      liveState = "error";
      // browser auto-reconnects; on success the open handler flips us back
    };
  }

  function closeStream(): void {
    source?.close();
    source = null;
  }

  async function backfill(): Promise<void> {
    try {
      const resp = await api.mqttFeed(100);
      // Backend returns items already; sort newest-first for safety.
      const sorted = [...resp.items].sort((a, b) => b.ts - a.ts);
      items = sorted.slice(0, MAX_ITEMS);
    } catch {
      // ignore — SSE will populate live regardless
    }
  }

  onMount(() => {
    void backfill();
    openStream();
  });

  onDestroy(() => {
    closeStream();
  });

  const dotClass = $derived(
    liveState === "open"
      ? "bg-brand-emerald"
      : liveState === "connecting"
        ? "bg-brand-amber"
        : "bg-brand-red",
  );

  const dotLabel = $derived(
    liveState === "open"
      ? "live"
      : liveState === "connecting"
        ? "connecting"
        : "disconnected",
  );
</script>

<div class="space-y-6">
  <header class="flex items-center justify-between">
    <h1 class="text-lg font-semibold">MQTT feed</h1>
    <div class="flex items-center gap-2 text-xs text-text-muted">
      <span
        class="inline-block h-2 w-2 rounded-full {dotClass}"
        class:animate-pulse={liveState === "connecting"}
        aria-hidden="true"
      ></span>
      <span>{dotLabel}</span>
    </div>
  </header>

  <p class="text-xs text-text-muted">
    Live MQTT messages observed by ingest, streamed over SSE. Latest message at the top;
    capped at {MAX_ITEMS} entries.
  </p>

  <MqttFeed {items} {flashKey} />
</div>
