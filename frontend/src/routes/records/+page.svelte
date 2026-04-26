<script lang="ts">
  import { onMount } from "svelte";

  import HeroRecords from "$lib/components/HeroRecords.svelte";
  import { api } from "$lib/api";
  import type { Reading } from "$lib/types/api";

  let items = $state<Reading[]>([]);
  let total = $state(0);
  let limit = $state(100);
  let offset = $state(0);
  let loading = $state(false);
  let error = $state<string | null>(null);

  async function refresh() {
    loading = true;
    error = null;
    try {
      const resp = await api.readings({ limit, offset, order: "desc" });
      items = resp.items;
      total = resp.total;
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  onMount(refresh);

  function next() {
    if (offset + limit < total) {
      offset = offset + limit;
      void refresh();
    }
  }
  function prev() {
    if (offset > 0) {
      offset = Math.max(0, offset - limit);
      void refresh();
    }
  }

  async function del(date: string) {
    if (!confirm(`Delete reading at ${date}?`)) return;
    await api.deleteReading(date);
    await refresh();
  }
</script>

<div class="space-y-6">
  <HeroRecords size="full" />

  <div class="rounded-lg border border-border bg-bg-panel">
  <header class="flex items-center justify-between border-b border-border px-4 py-3">
    <h2 class="text-sm font-semibold">Readings</h2>
    <div class="text-xs text-text-muted tabular-nums">
      {total} rows · showing {offset + 1}–{Math.min(offset + limit, total)}
    </div>
  </header>

  {#if error}
    <p class="px-4 py-3 text-xs text-brand-red">{error}</p>
  {/if}

  <div class="overflow-x-auto">
    <table class="w-full text-sm tabular">
      <thead class="bg-bg-elev text-xs text-text-label">
        <tr>
          <th class="px-3 py-2 text-left">Date</th>
          <th class="px-3 py-2 text-right">Litres</th>
          <th class="px-3 py-2 text-right">%</th>
          <th class="px-3 py-2 text-right">Used</th>
          <th class="px-3 py-2 text-right">Temp</th>
          <th class="px-3 py-2 text-left">Refill</th>
          <th class="px-3 py-2 text-left">Leak</th>
          <th class="px-3 py-2"></th>
        </tr>
      </thead>
      <tbody>
        {#each items as row (row.date + row.id)}
          <tr class="border-t border-border">
            <td class="px-3 py-1.5 font-mono text-xs">{row.date}</td>
            <td class="px-3 py-1.5 text-right font-mono"
              >{row.litres_remaining?.toFixed(1) ?? "—"}</td
            >
            <td class="px-3 py-1.5 text-right font-mono"
              >{row.percentage_remaining?.toFixed(1) ?? "—"}</td
            >
            <td class="px-3 py-1.5 text-right font-mono"
              >{row.litres_used_since_last?.toFixed(1) ?? "—"}</td
            >
            <td class="px-3 py-1.5 text-right font-mono"
              >{row.temperature?.toFixed(1) ?? "—"}</td
            >
            <td class="px-3 py-1.5"
              >{#if row.refill_detected === "y"}<span
                  class="text-brand-emerald">y</span
                >{:else}n{/if}</td
            >
            <td class="px-3 py-1.5"
              >{#if row.leak_detected === "y"}<span class="text-brand-red"
                  >y</span
                >{:else}n{/if}</td
            >
            <td class="px-3 py-1.5 text-right">
              <button
                class="text-xs text-text-subtle hover:text-brand-red"
                on:click={() => del(row.date)}>delete</button
              >
            </td>
          </tr>
        {/each}
        {#if !items.length && !loading}
          <tr>
            <td class="px-3 py-6 text-center text-text-subtle" colspan="8"
              >No readings yet</td
            >
          </tr>
        {/if}
      </tbody>
    </table>
  </div>

  <footer class="flex items-center justify-end gap-2 border-t border-border px-4 py-3 text-xs">
    <button
      class="rounded border border-border px-2 py-1 disabled:opacity-50"
      on:click={prev}
      disabled={offset === 0 || loading}>← prev</button
    >
    <button
      class="rounded border border-border px-2 py-1 disabled:opacity-50"
      on:click={next}
      disabled={offset + limit >= total || loading}>next →</button
    >
  </footer>
  </div>
</div>
