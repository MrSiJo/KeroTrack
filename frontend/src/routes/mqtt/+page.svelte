<script lang="ts">
  import { onMount } from "svelte";

  import { api } from "$lib/api";

  type FeedItem = { topic: string; payload: unknown; ts: number };
  let items = $state<FeedItem[]>([]);
  let loading = $state(false);

  async function refresh() {
    loading = true;
    try {
      const resp = await api.mqttFeed(100);
      items = resp.items;
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void refresh();
    const interval = setInterval(refresh, 10000);
    return () => clearInterval(interval);
  });

  function fmtTs(ts: number): string {
    return new Date(ts * 1000).toLocaleTimeString();
  }
</script>

<div class="space-y-6">
  <header class="flex items-center justify-between">
    <h1 class="text-lg font-semibold">MQTT feed</h1>
    <button
      class="rounded border border-border px-2 py-1 text-xs text-text-muted"
      on:click={refresh}
      disabled={loading}
    >
      {loading ? "…" : "refresh"}
    </button>
  </header>

  <p class="text-xs text-text-muted">
    Recent MQTT messages observed by ingest. The live SSE feed (Phase 7h) lands here
    when a real broker is wired up via Settings.
  </p>

  <div class="rounded-lg border border-border bg-bg-panel">
    <div class="divide-y divide-border">
      {#each items as item}
        <article class="flex items-start gap-4 px-4 py-2.5 font-mono text-xs">
          <span class="text-text-subtle">{fmtTs(item.ts)}</span>
          <span class="text-brand-blue-2">{item.topic}</span>
          <pre class="flex-1 whitespace-pre-wrap break-all">{JSON.stringify(item.payload)}</pre>
        </article>
      {/each}
      {#if !items.length}
        <p class="px-4 py-6 text-center text-xs text-text-subtle">No messages yet.</p>
      {/if}
    </div>
  </div>
</div>
