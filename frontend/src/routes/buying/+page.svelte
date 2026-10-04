<script lang="ts">
  import { onMount } from "svelte";

  import { api } from "$lib/api";
  import {
    daysUntil,
    formatAge,
    formatGBP,
    fixed,
    formatPpl,
    isoToday,
    latestQuotes,
    relativeDays,
    scenarioLabel,
    stateLabel,
    stateTone,
    supplierName,
    type Tone,
  } from "$lib/buying";
  import PriceHistoryChart from "$lib/components/PriceHistoryChart.svelte";
  import RunwayChart from "$lib/components/RunwayChart.svelte";
  import StatCard from "$lib/components/StatCard.svelte";
  import { settings } from "$lib/stores/settings";
  import type {
    BuyingCalibration,
    BuyingQuote,
    BuyingSummary,
  } from "$lib/types/api";

  let summary = $state<BuyingSummary | null>(null);
  let history = $state<BuyingQuote[]>([]);
  let error = $state<string | null>(null);
  let loading = $state(true);
  let running = $state(false);
  let calibrating = $state(false);
  let calibration = $state<BuyingCalibration | null>(null);
  let calError = $state<string | null>(null);

  async function load() {
    try {
      const [s, q] = await Promise.all([
        api.getBuyingSummary(),
        api.getBuyingQuotes(90),
      ]);
      summary = s;
      history = q.items;
      stamp();
      error = null;
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void load();
    void settings.refresh();
  });

  async function runNow() {
    running = true;
    try {
      summary = await api.runBuying();
      history = (await api.getBuyingQuotes(90)).items;
      stamp();
      error = null;
    } catch (err) {
      error = (err as Error).message;
    } finally {
      running = false;
    }
  }

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

  const toneClass: Record<Tone, string> = {
    green: "border-brand-emerald text-brand-emerald",
    amber: "border-brand-amber text-brand-amber",
    red: "border-brand-red text-brand-red",
    neutral: "border-border text-text-muted",
  };

  let today = $state(isoToday());
  let now = $state(new Date());

  function stamp() {
    today = isoToday();
    now = new Date();
  }

  let scenario = $derived(
    summary ? summary.scenarios[summary.active_scenario ?? "normal"] : undefined,
  );
  let orderBy = $derived(scenario?.order_by ?? null);
  let reserve = $derived.by(() => {
    const item = $settings.items.find((i) => i.key === "projection.reserve_l");
    const v = Number(item?.value);
    return item && Number.isFinite(v) && v > 0 ? v : 100;
  });
  let rows = $derived(latestQuotes(summary?.quotes ?? []));
  let change = $derived(summary?.context.best_change_30d ?? null);

  function f1(n: number | null | undefined): string {
    return typeof n === "number" && Number.isFinite(n) ? n.toFixed(1) : "n/a";
  }
</script>

<div class="space-y-6">
  <div class="flex items-center justify-between">
    <h1 class="text-lg font-semibold text-text">Oil buying</h1>
    <button
      class="rounded border border-border px-3 py-1 text-sm text-text-muted hover:text-brand-blue disabled:opacity-50"
      disabled={running}
      onclick={runNow}
    >
      {running ? "Checking prices..." : "Check prices now"}
    </button>
  </div>

  {#if error}
    <p class="rounded border border-brand-red p-3 text-sm text-brand-red">
      Could not load buying data: {error}
    </p>
  {/if}

  {#if loading}
    <p class="text-sm text-text-muted">Loading...</p>
  {:else if summary}
    <!-- 1. State banner -->
    <section
      class={`rounded-lg border-2 bg-bg-panel p-4 ${toneClass[stateTone(summary.state)]}`}
    >
      <div class="text-xl font-semibold">{stateLabel(summary.state)}</div>
      <div class="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          label="Best total"
          value={summary.best ? formatGBP(summary.best.total_inc_vat) : "n/a"}
          sub={summary.best
            ? `${supplierName(summary.best.supplier)}${summary.best.delivery_label ? `, ${summary.best.delivery_label}` : ""}`
            : "No quote available"}
        />
        <StatCard
          label="Effective price"
          value={summary.best ? formatPpl(summary.best.ppl_effective) : "n/a"}
          sub={`Trigger ${formatPpl(summary.trigger_ppl)}`}
        />
        <StatCard
          label="Order by"
          value={orderBy ?? "n/a"}
          sub={orderBy ? relativeDays(daysUntil(orderBy, today)) : ""}
        />
        <StatCard
          label="Headroom"
          value={f1(summary.headroom_l)}
          unit="L"
          sub="Room in the tank for a delivery"
        />
      </div>
      {#if change !== null}
        <p class="mt-3 text-xs text-text-muted">
          Best price is {change > 0 ? "up" : change < 0 ? "down" : "unchanged"}
          {change !== 0 ? `${Math.abs(change).toFixed(1)}p ` : ""}on 30 days ago.
        </p>
      {/if}
      {#if summary.updated_at}
        <p class="mt-1 text-xs text-text-subtle">
          Updated {formatAge(summary.updated_at, now)}
        </p>
      {/if}
    </section>

    <!-- 2. Quotes table -->
    <section>
      <h2 class="mb-2 text-sm font-semibold text-text">Latest quotes</h2>
      {#if rows.length === 0}
        <p class="text-sm text-text-muted">No quotes yet.</p>
      {:else}
        <div class="overflow-x-auto rounded-lg border border-border bg-bg-panel">
          <table class="w-full text-left text-sm">
            <thead class="text-[10px] uppercase tracking-wide text-text-label">
              <tr>
                <th class="px-3 py-2">Supplier</th>
                <th class="px-3 py-2">Delivery</th>
                <th class="px-3 py-2 text-right">Total</th>
                <th class="px-3 py-2 text-right">Effective</th>
                <th class="px-3 py-2 text-right">Fees</th>
                <th class="px-3 py-2">Age</th>
              </tr>
            </thead>
            <tbody>
              {#each rows as r (r.id)}
                <tr class="border-t border-border" class:text-text-subtle={!!r.urgent}>
                  <td class="px-3 py-1.5">{supplierName(r.supplier)}</td>
                  <td class="px-3 py-1.5">
                    {r.delivery_label ?? "n/a"}
                    {#if !r.urgent}
                      <span class="ml-1 rounded bg-bg-elev px-1.5 py-0.5 text-[10px] text-brand-blue">
                        default
                      </span>
                    {/if}
                  </td>
                  {#if r.ok}
                    <td class="px-3 py-1.5 text-right font-mono">{formatGBP(r.total_inc_vat)}</td>
                    <td class="px-3 py-1.5 text-right font-mono">{formatPpl(r.ppl_effective)}</td>
                    <td class="px-3 py-1.5 text-right font-mono">{formatGBP(r.fees_inc_vat ?? 0)}</td>
                  {:else}
                    <td colspan="3" class="px-3 py-1.5 text-brand-red">
                      Failed{r.error ? `: ${r.error}` : ""}
                    </td>
                  {/if}
                  <td class="px-3 py-1.5 text-xs text-text-muted">{formatAge(r.fetched_at, now)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <p class="mt-1 text-xs text-text-subtle">
          Faster delivery windows cost more and are shown dimmed. The standard delivery is the default.
        </p>
      {/if}
    </section>

    <!-- 3. Price history -->
    <section>
      <h2 class="mb-2 text-sm font-semibold text-text">Price history</h2>
      <PriceHistoryChart quotes={history} trigger={summary.trigger_ppl} />
    </section>

    <!-- 4. Runway -->
    <section>
      <h2 class="mb-2 text-sm font-semibold text-text">Tank runway</h2>
      <RunwayChart scenarios={summary.scenarios} {reserve} />
      <ul class="mt-2 grid gap-1 text-xs text-text-muted md:grid-cols-3">
        {#each Object.entries(summary.scenarios) as [key, sc] (key)}
          <li>
            <span class="text-text">{scenarioLabel(key)}</span>:
            runs out {sc.run_out ?? "n/a"}, order by {sc.order_by ?? "n/a"}
          </li>
        {/each}
      </ul>
    </section>

    <!-- 5. Calibration -->
    <section class="rounded-lg border border-border bg-bg-panel p-4">
      <h2 class="mb-2 text-sm font-semibold text-text">Calibration</h2>
      <div class="grid grid-cols-2 gap-3 md:grid-cols-3">
        <StatCard label="Heating factor (k)" value={fixed(summary.k, 3)} sub="Litres per heating degree day" compact />
        <StatCard label="Hot water" value={f1(summary.hw_l_per_day)} unit="L/day" compact />
      </div>
      <div class="mt-3 flex items-center gap-3">
        <button
          class="rounded border border-border px-3 py-1 text-sm text-text-muted hover:text-brand-blue disabled:opacity-50"
          disabled={calibrating}
          onclick={calibrate}
        >
          {calibrating ? "Calibrating..." : "Calibrate"}
        </button>
        <a href="/settings" class="text-sm text-brand-blue">Open Settings to accept a proposal</a>
      </div>
      {#if calError}
        <p class="mt-2 text-sm text-brand-red">Calibration failed: {calError}</p>
      {/if}
      {#if calibration}
        <div class="mt-3 space-y-1 text-sm text-text-muted">
          <p>
            Proposed k: <span class="font-mono text-text">{fixed(calibration.k, 3)}</span>
            (fitted over {calibration.days_used} days, {calibration.heating_days} heating days, error {fixed(calibration.mae_l, 1)} L).
          </p>
          <p>
            Hot water: <span class="font-mono text-text">{f1(calibration.hw_fixed_l)} L/day</span>
            (now {f1(calibration.current_hw_l_per_day)} L/day).
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
              Not enough summer data to propose; set burner minutes in Settings &gt; boiler.
            </p>
          {:else}
            <p>
              Proposed burner minutes:
              <span class="font-mono text-text">{fixed(calibration.proposed_burner_minutes, 1)}</span>
              (now {calibration.current_burner_minutes ?? "n/a"}).
            </p>
          {/if}
        </div>
      {/if}
    </section>
  {/if}
</div>
