<script lang="ts">
  import { onMount } from "svelte";

  import StatCard from "$lib/components/StatCard.svelte";
  import { api } from "$lib/api";
  import type { AnalysisResult } from "$lib/types/api";

  let analysis = $state<AnalysisResult | null>(null);
  let error = $state<string | null>(null);

  onMount(async () => {
    try {
      analysis = await api.analysisLatest();
    } catch (err) {
      error = (err as Error).message;
    }
  });
</script>

<div class="space-y-6">
  <h1 class="text-lg font-semibold">Forecast</h1>
  <p class="text-xs text-text-muted">
    Phase 7f — fan chart (median, p25/p75, p5/p95) + scenario table land here. For
    now we surface the latest analysis estimates directly so the data is visible.
  </p>

  {#if error}
    <p class="text-xs text-brand-red">{error}</p>
  {:else if analysis}
    <section class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatCard
        label="Days remaining"
        value={analysis.estimated_days_remaining?.toFixed(0) ?? "—"}
        unit="days"
      />
      <StatCard
        label="Empty by"
        value={analysis.estimated_empty_date ?? "—"}
      />
      <StatCard
        label="Avg daily L"
        value={analysis.avg_daily_consumption_l?.toFixed(1) ?? "—"}
        unit="L/day"
      />
      <StatCard
        label="Heating split"
        value={analysis.estimated_daily_heating_consumption_l?.toFixed(1) ?? "—"}
        unit="L/day"
        sub="seasonal heating factor {analysis.seasonal_heating_factor ?? '—'}"
      />
    </section>
  {/if}
</div>
