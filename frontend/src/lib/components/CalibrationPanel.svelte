<script lang="ts">
  import { onMount } from "svelte";

  import { api } from "$lib/api";
  import { fixed } from "$lib/buying";
  import StatCard from "$lib/components/StatCard.svelte";
  import { heatingModelLabel, nestMonthsText } from "$lib/countdown";
  import type { BuyingCalibration, HeatingModel } from "$lib/types/api";

  type Props = {
    /** Stage a proposed burner minutes value in the settings form (not saved). */
    onUseMinutes?: (minutes: number) => void;
  };
  let { onUseMinutes }: Props = $props();

  let k = $state<number | null>(null);
  let hw = $state<number | null>(null);
  let model = $state<HeatingModel | null>(null);
  let lPerHour = $state<number | null>(null);
  let calibrating = $state(false);
  let calibration = $state<BuyingCalibration | null>(null);
  let calError = $state<string | null>(null);

  onMount(async () => {
    try {
      const s = await api.getBuyingSummary();
      k = s.k;
      hw = s.hw_l_per_day;
      model = s.heating_model ?? null;
      lPerHour = s.l_per_heating_hour ?? null;
    } catch {
      /* the figures stay n/a */
    }
  });

  async function calibrate() {
    calibrating = true;
    calError = null;
    try {
      calibration = await api.calibrateBuying();
    } catch (err) {
      calError = (err as Error).message;
    } finally {
      calibrating = false;
    }
  }
</script>

<div class="bg-bg-elev/40 px-4 py-3">
  <div class="mb-2 text-xs font-medium uppercase tracking-wide text-text-muted">Calibration</div>
  <p class="mb-2 text-sm text-text-muted">
    Heating model: <span class="text-text">{heatingModelLabel(model)}</span>
  </p>
  <div class="grid grid-cols-2 gap-3 md:grid-cols-3">
    {#if model === "nest"}
      <StatCard label="Heating" value={fixed(lPerHour, 2)} unit="L per heating hour" sub="From your Nest heating hours" compact />
    {:else}
      <StatCard label="Heating factor (k)" value={fixed(k, 3)} sub="Litres per heating degree day" compact />
    {/if}
    <StatCard label="Hot water" value={fixed(hw, 1)} unit="L/day" compact />
  </div>
  <div class="mt-3 flex items-center gap-3">
    <button
      type="button"
      class="rounded border border-border px-3 py-1 text-sm text-text-muted hover:text-brand-blue disabled:opacity-50"
      disabled={calibrating}
      onclick={calibrate}
    >
      {calibrating ? "Calibrating..." : "Calibrate"}
    </button>
    <span class="text-[11px] text-text-subtle">Previews a fit from your readings. Nothing is saved.</span>
  </div>
  {#if calError}
    <p class="mt-2 text-sm text-brand-red">Calibration failed: {calError}</p>
  {/if}
  {#if calibration}
    <div class="mt-3 space-y-1 text-sm text-text-muted">
      <p>
        Model used for this fit:
        <span class="text-text">{heatingModelLabel(calibration.heating_model)}</span>.
      </p>
      {#if calibration.heating_model === "nest"}
        <p>
          Litres per heating hour:
          <span class="font-mono text-text">{fixed(calibration.l_per_heating_hour, 2)}</span>
          (free fit {fixed(calibration.l_per_heating_hour_free, 2)}).
          Hot water under this model: {fixed(calibration.hw_per_day_nest, 1)} L/day.
        </p>
        <p>{nestMonthsText(calibration.nest_months_used, calibration.nest_months_excluded)}.</p>
      {/if}
      <p>
        Proposed k: <span class="font-mono text-text">{fixed(calibration.k, 3)}</span>
        (fitted over {calibration.days_used} days, {calibration.heating_days} heating days, error {fixed(calibration.mae_l, 1)} L).
      </p>
      <p>
        Hot water: <span class="font-mono text-text">{fixed(calibration.hw_fixed_l, 1)} L/day</span>
        (now {fixed(calibration.current_hw_l_per_day, 1)} L/day).
        {#if calibration.hw_floor_l != null}
          Summer floor estimate: {fixed(calibration.hw_floor_l, 1)} L/day.
        {/if}
      </p>
      {#if calibration.free_hw_l != null && calibration.free_k != null}
        <p>
          Free fit: {fixed(calibration.free_hw_l, 2)} L/day hot water, k {fixed(calibration.free_k, 3)}.
        </p>
      {/if}
      {#if calibration.proposed_burner_minutes == null}
        <p class="text-brand-amber">
          Not enough summer data to propose burner minutes; set them by hand above.
        </p>
      {:else}
        <p>
          Proposed burner minutes:
          <span class="font-mono text-text">{fixed(calibration.proposed_burner_minutes, 1)}</span>
          (now {fixed(calibration.current_burner_minutes, 1)}).
          {#if onUseMinutes}
            {@const proposed = calibration.proposed_burner_minutes}
            <button
              type="button"
              class="ml-1 text-brand-blue"
              onclick={() => onUseMinutes?.(Math.round(proposed * 2) / 2)}
            >
              Use this value
            </button>
            <span class="text-[11px] text-text-subtle">(then Save)</span>
          {/if}
        </p>
      {/if}
    </div>
  {/if}
</div>
