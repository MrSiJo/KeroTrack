<script lang="ts">
  import { onMount } from "svelte";

  import StatCard from "$lib/components/StatCard.svelte";
  import { api } from "$lib/api";

  let summary = $state<Record<string, unknown> | null>(null);
  let periods = $state<Record<string, unknown>[]>([]);
  let error = $state<string | null>(null);

  onMount(async () => {
    try {
      summary = await api.costsSummary();
    } catch (err) {
      const msg = (err as Error).message;
      if (!msg.includes("no_cost_analysis")) error = msg;
    }
    try {
      const p = await api.costPeriods();
      periods = p.items;
    } catch (err) {
      error = (err as Error).message;
    }
  });

  function fmtCost(n: unknown): string {
    if (typeof n !== "number" || !Number.isFinite(n)) return "—";
    return n.toFixed(2);
  }
</script>

<div class="space-y-6">
  <h1 class="text-lg font-semibold">Costs</h1>

  {#if error}
    <p class="text-xs text-brand-red">{error}</p>
  {/if}

  {#if summary}
    <section class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatCard
        label="Avg daily"
        value={fmtCost(summary.avg_daily_cost)}
        unit="£"
      />
      <StatCard
        label="Avg monthly"
        value={fmtCost(summary.avg_monthly_cost)}
        unit="£"
      />
      <StatCard
        label="Avg annual"
        value={fmtCost(summary.avg_annual_cost)}
        unit="£"
      />
      <StatCard
        label="Refill periods"
        value={String(summary.total_refill_periods ?? "—")}
      />
    </section>
  {:else}
    <p class="text-xs text-text-muted">
      No cost analysis run yet. Phase 7g — ppl history + per-period table + energy
      efficiency bars land here.
    </p>
  {/if}

  {#if periods.length}
    <div class="rounded-lg border border-border bg-bg-panel">
      <header class="border-b border-border px-4 py-2 text-sm font-semibold">
        Refill periods
      </header>
      <div class="overflow-x-auto">
        <table class="w-full text-sm tabular">
          <thead class="bg-bg-elev text-xs text-text-label">
            <tr>
              <th class="px-3 py-2 text-left">Start</th>
              <th class="px-3 py-2 text-left">End</th>
              <th class="px-3 py-2 text-right">Days</th>
              <th class="px-3 py-2 text-right">Litres</th>
              <th class="px-3 py-2 text-right">Cost £</th>
              <th class="px-3 py-2 text-right">Daily £</th>
              <th class="px-3 py-2 text-right">PPL</th>
            </tr>
          </thead>
          <tbody>
            {#each periods as p}
              <tr class="border-t border-border">
                <td class="px-3 py-1.5 font-mono text-xs">{p.start_date}</td>
                <td class="px-3 py-1.5 font-mono text-xs">{p.end_date}</td>
                <td class="px-3 py-1.5 text-right font-mono">{p.days ?? "—"}</td>
                <td class="px-3 py-1.5 text-right font-mono"
                  >{fmtCost(p.total_consumption)}</td
                >
                <td class="px-3 py-1.5 text-right font-mono">{fmtCost(p.total_cost)}</td>
                <td class="px-3 py-1.5 text-right font-mono">{fmtCost(p.daily_cost)}</td>
                <td class="px-3 py-1.5 text-right font-mono">{fmtCost(p.refill_ppl)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
</div>
