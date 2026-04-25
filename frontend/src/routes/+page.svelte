<script lang="ts">
  import { onMount } from "svelte";

  import StatCard from "$lib/components/StatCard.svelte";
  import TankSilhouette from "$lib/components/TankSilhouette.svelte";
  import { liveStatus } from "$lib/stores/liveStatus";

  onMount(() => {
    void liveStatus.refresh();
  });

  function fmtL(v: number | null | undefined): string {
    return v == null ? "—" : Math.round(v).toString();
  }
  function fmtPct(v: number | null | undefined): string {
    return v == null ? "—" : v.toFixed(0);
  }
</script>

<div class="grid grid-cols-12 gap-6">
  <section class="col-span-12 lg:col-span-5">
    <div
      class="flex h-full flex-col items-center justify-center rounded-lg border border-border bg-bg-panel p-6"
    >
      <TankSilhouette
        percentage={$liveStatus.status?.reading?.percentage_remaining ?? 0}
      />
      <div class="mt-4 font-mono text-3xl font-semibold text-text">
        {fmtL($liveStatus.status?.reading?.litres_remaining)} L
      </div>
      <div class="mt-1 text-xs text-text-muted">
        Last reading: {$liveStatus.status?.reading?.date ?? "—"}
      </div>
    </div>
  </section>

  <section class="col-span-12 lg:col-span-7 grid grid-cols-2 gap-3">
    <StatCard
      label="Percentage"
      value={fmtPct($liveStatus.status?.reading?.percentage_remaining)}
      unit="%"
    />
    <StatCard
      label="Cost to fill"
      value={$liveStatus.status?.reading?.cost_to_fill ?? "—"}
      unit="£"
    />
    <StatCard
      label="Days remaining"
      value={
        $liveStatus.status?.analysis?.estimated_days_remaining != null
          ? $liveStatus.status.analysis.estimated_days_remaining.toFixed(0)
          : "—"
      }
      unit="days"
    />
    <StatCard
      label="Avg daily use"
      value={
        $liveStatus.status?.analysis?.avg_daily_consumption_l != null
          ? $liveStatus.status.analysis.avg_daily_consumption_l.toFixed(1)
          : "—"
      }
      unit="L/day"
    />
    <StatCard
      label="Temperature"
      value={
        $liveStatus.status?.reading?.temperature != null
          ? $liveStatus.status.reading.temperature.toFixed(1)
          : "—"
      }
      unit="°C"
    />
    <StatCard
      label="Current ppl"
      value={
        $liveStatus.status?.reading?.current_ppl != null
          ? $liveStatus.status.reading.current_ppl.toFixed(2)
          : "—"
      }
      unit="p/L"
    />
  </section>

  {#if $liveStatus.status?.reading == null}
    <p class="col-span-12 text-sm text-text-muted">
      No readings yet — point <code class="font-mono">mqtt.broker</code> at your real
      broker via Settings, or run the Phase 6 migrator to import a v1 snapshot.
    </p>
  {/if}
</div>
