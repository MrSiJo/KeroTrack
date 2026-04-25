<script lang="ts">
  import { onMount } from "svelte";

  import { api } from "$lib/api";
  import type { Reading } from "$lib/types/api";

  let readings = $state<Reading[]>([]);
  let loading = $state(false);

  onMount(async () => {
    loading = true;
    try {
      const resp = await api.readings({ limit: 500, order: "desc" });
      readings = resp.items.reverse();
    } finally {
      loading = false;
    }
  });
</script>

<div class="space-y-6">
  <h1 class="text-lg font-semibold">Trends</h1>
  <p class="text-xs text-text-muted">
    Phase 7e — full ECharts dual-axis level + temperature, daily-consumption bars,
    HDD scatter and calendar heatmap land here. Showing a basic time-ordered table
    in the meantime so the data is at least visible.
  </p>

  <div class="rounded-lg border border-border bg-bg-panel p-3">
    {#if loading}
      <p class="text-xs text-text-subtle">Loading…</p>
    {:else if !readings.length}
      <p class="text-xs text-text-subtle">No readings yet.</p>
    {:else}
      <div class="font-mono text-xs">
        <div class="text-text-muted">
          first {readings.at(0)?.date} → last {readings.at(-1)?.date}
        </div>
        <div class="mt-2">{readings.length} samples in window</div>
      </div>
    {/if}
  </div>
</div>
