<script lang="ts">
  import { onMount } from "svelte";

  import { api } from "$lib/api";
  import {
    daysUntil,
    isoToday,
    relativeDays,
    stateLabel,
    stateTone,
    type Tone,
  } from "$lib/buying";
  import type { BuyingSummary } from "$lib/types/api";

  let summary = $state<BuyingSummary | null>(null);
  let failed = $state(false);
  let today = $state(isoToday());

  onMount(async () => {
    try {
      summary = await api.getBuyingSummary();
      today = isoToday();
    } catch {
      failed = true;
    }
  });

  const toneClass: Record<Tone, string> = {
    green: "border-brand-emerald text-brand-emerald",
    amber: "border-brand-amber text-brand-amber",
    red: "border-brand-red text-brand-red",
    neutral: "border-border text-text-muted",
  };

  let orderBy = $derived(
    summary?.scenarios?.[summary.active_scenario ?? "normal"]?.order_by ?? null,
  );
</script>

{#if !failed}
  <a
    href="/buying"
    class={`flex items-center justify-between rounded-lg border bg-bg-panel px-4 py-2 text-sm ${toneClass[stateTone(summary?.state)]}`}
  >
    <span class="font-semibold">
      Oil buying: {summary ? stateLabel(summary.state) : "loading"}
    </span>
    {#if orderBy}
      <span class="text-xs text-text-muted">
        Order by {orderBy} ({relativeDays(daysUntil(orderBy, today))})
      </span>
    {/if}
  </a>
{/if}
