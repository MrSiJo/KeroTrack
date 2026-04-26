<script lang="ts">
  import { onMount } from "svelte";

  import StatCard from "$lib/components/StatCard.svelte";
  import TankSilhouette from "$lib/components/TankSilhouette.svelte";
  import { liveStatus } from "$lib/stores/liveStatus";
  import { settings } from "$lib/stores/settings";

  onMount(() => {
    void liveStatus.refresh();
    void settings.refresh();
  });

  function setting(key: string): unknown {
    return $settings.items.find((i) => i.key === key)?.value;
  }

  let reading = $derived($liveStatus.status?.reading);
  let analysis = $derived($liveStatus.status?.analysis);
  let cost = $derived(
    $liveStatus.status?.cost as Record<string, unknown> | null,
  );

  let capacity = $derived(Number(setting("tank.capacity_l") ?? 1225));
  let lengthCm = $derived(Number(setting("tank.length_cm") ?? 178.5));
  let heightCm = $derived(Number(setting("tank.height_cm") ?? 137));
  let lowThreshold = $derived(
    Number(setting("alerts.low_level_threshold_pct") ?? 20),
  );

  let pct = $derived(reading?.percentage_remaining ?? 0);
  let levelTone = $derived<"default" | "amber" | "red">(
    pct <= lowThreshold * 0.5
      ? "red"
      : pct <= lowThreshold
        ? "amber"
        : "default",
  );

  function fmtNum(v: number | null | undefined, digits = 0): string {
    return v == null || !Number.isFinite(v) ? "—" : v.toFixed(digits);
  }
</script>

<div class="grid grid-cols-12 gap-4">
  <!-- Tank hero -->
  <section class="col-span-12 lg:col-span-5">
    <div class="rounded-lg border border-border bg-bg-panel p-4">
      <div class="text-[10px] uppercase tracking-wide text-text-label">
        Tank level
      </div>
      <div class="mt-3">
        <TankSilhouette
          percentage={pct}
          litres={reading?.litres_remaining ?? null}
          capacity={capacity}
          bars={reading?.bars_remaining ?? null}
          {lengthCm}
          {heightCm}
        />
      </div>
      <div
        class="mt-3 flex items-baseline justify-between border-t border-border pt-2"
      >
        <div>
          <div class="font-mono text-2xl font-semibold text-text">
            {fmtNum(reading?.litres_remaining, 0)}
            <span class="text-sm text-text-muted">L</span>
          </div>
          <div class="text-[11px] text-text-subtle">
            of {Math.round(capacity)} L · {reading?.bars_remaining ?? "—"} bars
          </div>
        </div>
        <div class="text-right">
          <div class="text-[11px] text-text-subtle">Last reading</div>
          <div class="font-mono text-xs text-text-muted">
            {reading?.date ?? "—"}
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- Stats grid (no duplicate percentage card) -->
  <section class="col-span-12 lg:col-span-7">
    <div class="grid grid-cols-2 gap-3 md:grid-cols-3">
      <StatCard
        label="Cost to fill"
        value={reading?.cost_to_fill ?? "—"}
        unit="£"
        tone={levelTone === "red" ? "red" : "default"}
        compact
      />
      <StatCard
        label="Days remaining"
        value={fmtNum(analysis?.estimated_days_remaining, 0)}
        unit="days"
        sub={analysis?.estimated_empty_date
          ? `empty ~ ${analysis.estimated_empty_date}`
          : ""}
        tone={analysis?.estimated_days_remaining != null &&
        analysis.estimated_days_remaining < 30
          ? "amber"
          : "default"}
        compact
      />
      <StatCard
        label="Avg daily use"
        value={fmtNum(analysis?.avg_daily_consumption_l, 1)}
        unit="L/day"
        compact
      />
      <StatCard
        label="Litres to order"
        value={fmtNum(reading?.litres_to_order, 0)}
        unit="L"
        compact
      />
      <StatCard
        label="Temperature"
        value={fmtNum(reading?.temperature, 1)}
        unit="°C"
        compact
      />
      <StatCard
        label="Current ppl"
        value={fmtNum(reading?.current_ppl, 2)}
        unit="p/L"
        compact
      />
      <StatCard
        label="Days since refill"
        value={fmtNum(analysis?.days_since_refill, 0)}
        unit="days"
        compact
      />
      <StatCard
        label="Avg daily cost"
        value={fmtNum(cost?.avg_daily_cost as number | null, 2)}
        unit="£"
        compact
      />
      <StatCard
        label="HDD this period"
        value={fmtNum(analysis?.upcoming_month_hdd, 1)}
        compact
      />
    </div>

    <div class="mt-3 flex flex-wrap gap-2">
      {#if reading?.refill_detected === "y"}
        <div
          class="rounded border border-brand-emerald/40 bg-emerald-950/40 px-3 py-1.5 text-xs text-brand-emerald"
        >
          Refill detected
        </div>
      {/if}
      {#if reading?.leak_detected === "y"}
        <div
          class="rounded border border-brand-red/40 bg-red-950/40 px-3 py-1.5 text-xs text-brand-red"
        >
          Leak detected
        </div>
      {/if}
      {#if levelTone === "red"}
        <div
          class="rounded border border-brand-red/40 bg-red-950/40 px-3 py-1.5 text-xs text-brand-red"
        >
          Critical level — order now
        </div>
      {:else if levelTone === "amber"}
        <div
          class="rounded border border-brand-amber/40 bg-amber-950/40 px-3 py-1.5 text-xs text-brand-amber"
        >
          Below {lowThreshold}% — plan a refill
        </div>
      {/if}
    </div>
  </section>

  {#if reading == null}
    <p class="col-span-12 text-sm text-text-muted">
      No readings yet — point <code class="font-mono">mqtt.broker</code> at your real
      broker via Settings, or run the Phase 6 migrator to import a v1 snapshot.
    </p>
  {/if}
</div>
