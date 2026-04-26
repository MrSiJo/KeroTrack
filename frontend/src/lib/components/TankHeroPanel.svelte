<script lang="ts">
  import TankSilhouette from "$lib/components/TankSilhouette.svelte";
  import { liveStatus } from "$lib/stores/liveStatus";
  import { settings } from "$lib/stores/settings";

  function setting(key: string): unknown {
    return $settings.items.find((i) => i.key === key)?.value;
  }

  let reading = $derived($liveStatus.status?.reading);
  let analysis = $derived($liveStatus.status?.analysis);

  let capacity = $derived(Number(setting("tank.capacity_l") ?? 1225));
  let lengthCm = $derived(Number(setting("tank.length_cm") ?? 178.5));
  let heightCm = $derived(Number(setting("tank.height_cm") ?? 137));
  let lowThreshold = $derived(
    Number(setting("alerts.low_level_threshold_pct") ?? 20),
  );

  let pct = $derived(reading?.percentage_remaining ?? 0);
  let bars = $derived(reading?.bars_remaining ?? null);
  let daysRemaining = $derived(analysis?.estimated_days_remaining ?? null);
  let costToFill = $derived(
    reading?.cost_to_fill != null && reading.cost_to_fill !== ""
      ? Number(reading.cost_to_fill)
      : null,
  );
  let currentPpl = $derived(
    reading?.current_ppl != null ? Number(reading.current_ppl) : null,
  );

  let levelTone = $derived<"default" | "amber" | "red">(
    pct <= lowThreshold * 0.5
      ? "red"
      : pct <= lowThreshold
        ? "amber"
        : "default",
  );
  let daysTone = $derived<"default" | "amber" | "red">(
    daysRemaining == null
      ? "default"
      : daysRemaining < 14
        ? "red"
        : daysRemaining < 30
          ? "amber"
          : "default",
  );

  function fmtNum(v: number | null | undefined, digits = 0): string {
    return v == null || !Number.isFinite(v) ? "—" : v.toFixed(digits);
  }

  const toneClass: Record<string, string> = {
    default: "text-text",
    amber: "text-brand-amber",
    red: "text-brand-red",
  };
</script>

<section class="relative overflow-hidden rounded-lg border border-border bg-bg-panel p-4">
  <div class="absolute left-0 top-0 h-full w-[3px] bg-brand-blue"></div>
  <div class="text-[10px] font-medium uppercase tracking-wide text-brand-blue">
    Now — Dashboard
  </div>

  <div class="mt-3 flex items-start gap-4">
    <div class="w-72 flex-shrink-0">
      <TankSilhouette
        percentage={pct}
        litres={reading?.litres_remaining ?? null}
        capacity={capacity}
        bars={bars}
        {lengthCm}
        {heightCm}
      />
    </div>

    <div class="flex flex-1 flex-col justify-between gap-3 self-stretch">
      <div>
        <div class="text-[10px] uppercase tracking-wide text-text-label">Bars · Remaining</div>
        <div class="mt-0.5 flex items-baseline gap-2 font-mono">
          <span class="text-2xl font-semibold text-text">{bars ?? "—"}<span class="text-sm text-text-muted">/10</span></span>
          <span class="text-text-subtle">·</span>
          <span class={`text-2xl font-semibold ${toneClass[levelTone]}`}>{fmtNum(pct, 0)}<span class="text-sm text-text-muted">%</span></span>
        </div>
        <div class="text-[11px] text-text-subtle">{fmtNum(reading?.litres_remaining, 0)} L / {Math.round(capacity)}</div>
      </div>

      <div>
        <div class="text-[10px] uppercase tracking-wide text-text-label">Days to empty</div>
        <div class="mt-0.5 font-mono">
          <span class={`text-xl font-semibold ${toneClass[daysTone]}`}>{fmtNum(daysRemaining, 0)}</span>
          {#if analysis?.estimated_empty_date}
            <span class="ml-2 text-[11px] text-text-subtle">~ {analysis.estimated_empty_date}</span>
          {/if}
        </div>
      </div>

      <div>
        <div class="text-[10px] uppercase tracking-wide text-text-label">Cost to fill</div>
        <div class="mt-0.5 font-mono">
          <span class="text-xl font-semibold text-text">£{fmtNum(costToFill as number | null | undefined, 0)}</span>
          {#if currentPpl != null}
            <span class="ml-2 text-[11px] text-text-subtle">@ {fmtNum(currentPpl, 2)} p/L</span>
          {/if}
        </div>
      </div>
    </div>
  </div>

  <div class="mt-3 flex items-center justify-between border-t border-border pt-2">
    <div class="flex flex-wrap gap-2">
      {#if reading?.refill_detected === "y"}
        <span class="rounded border border-brand-emerald/40 bg-emerald-950/40 px-2 py-1 text-[11px] text-brand-emerald">Refill detected</span>
      {/if}
      {#if reading?.leak_detected === "y"}
        <span class="rounded border border-brand-red/40 bg-red-950/40 px-2 py-1 text-[11px] text-brand-red">Leak detected</span>
      {/if}
      {#if levelTone === "red"}
        <span class="rounded border border-brand-red/40 bg-red-950/40 px-2 py-1 text-[11px] text-brand-red">Critical level — order now</span>
      {:else if levelTone === "amber"}
        <span class="rounded border border-brand-amber/40 bg-amber-950/40 px-2 py-1 text-[11px] text-brand-amber">Below {lowThreshold}% — plan a refill</span>
      {/if}
    </div>
    <div class="font-mono text-[11px] text-text-subtle">
      last reading {reading?.date ?? "—"}
    </div>
  </div>
</section>
