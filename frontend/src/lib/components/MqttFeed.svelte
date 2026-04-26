<script lang="ts">
  type FeedItem = { topic: string; payload: unknown; ts: number };

  type Props = {
    items: FeedItem[];
    flashKey?: number;
  };

  let { items, flashKey = 0 }: Props = $props();

  function fmtTs(ts: number): string {
    return new Date(ts * 1000).toLocaleTimeString();
  }

  function fmtPayload(payload: unknown): string {
    try {
      return JSON.stringify(payload);
    } catch {
      return String(payload);
    }
  }
</script>

<div class="rounded-lg border border-border bg-bg-panel">
  <div class="divide-y divide-border">
    {#each items as item, i (item.ts + ":" + item.topic + ":" + i)}
      <article
        class="flex items-start gap-4 px-4 py-2.5 font-mono text-xs"
        class:flash={i === 0 && flashKey > 0}
        data-flash-key={i === 0 ? flashKey : undefined}
      >
        <span class="text-text-subtle tabular-nums">{fmtTs(item.ts)}</span>
        <span class="text-brand-blue-2">{item.topic}</span>
        <pre class="flex-1 whitespace-pre-wrap break-all">{fmtPayload(item.payload)}</pre>
      </article>
    {/each}
    {#if !items.length}
      <p class="px-4 py-6 text-center text-xs text-text-subtle">
        Waiting for messages…
      </p>
    {/if}
  </div>
</div>

<style>
  @keyframes mqtt-flash {
    0% {
      background-color: rgb(var(--bg-panel));
      color: rgb(var(--text-default));
    }
    15% {
      background-color: rgba(245, 158, 11, 0.35);
      color: rgb(var(--text-default));
    }
    100% {
      background-color: rgb(var(--bg-panel));
      color: rgb(var(--text-default));
    }
  }

  .flash {
    animation: mqtt-flash 700ms ease-out;
  }
</style>
