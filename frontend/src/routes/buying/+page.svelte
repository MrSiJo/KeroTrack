<script lang="ts">
  import { onMount } from "svelte";

  import { api } from "$lib/api";
  import {
    fixed,
    formatAge,
    formatGBP,
    formatPpl,
    supplierName,
    allInPpl,
  } from "$lib/buying";
  import {
    formatDate,
    groupQuotesBySupplier,
    hasEnoughHistory,
    priceSummary,
    quoteDayCount,
  } from "$lib/countdown";
  import OrderCountdown from "$lib/components/OrderCountdown.svelte";
  import PriceHistoryChart from "$lib/components/PriceHistoryChart.svelte";
  import { settings } from "$lib/stores/settings";
  import type { BuyingQuote, BuyingSummary } from "$lib/types/api";

  const MIN_CHART_DAYS = 14;

  let summary = $state<BuyingSummary | null>(null);
  let history = $state<BuyingQuote[]>([]);
  let error = $state<string | null>(null);
  let loading = $state(true);
  let running = $state(false);
  let showAll = $state(false);
  let now = $state(new Date());

  async function load() {
    try {
      const [s, q] = await Promise.all([
        api.getBuyingSummary(),
        api.getBuyingQuotes(90),
      ]);
      summary = s;
      history = q.items;
      now = new Date();
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
      now = new Date();
      error = null;
    } catch (err) {
      error = (err as Error).message;
    } finally {
      running = false;
    }
  }

  let grouped = $derived(groupQuotesBySupplier(summary?.quotes ?? []));
  let rows = $derived(
    showAll
      ? [...grouped.primary, ...grouped.others].sort(
          (a, b) =>
            a.supplier.localeCompare(b.supplier) ||
            a.urgent - b.urgent ||
            (a.total_inc_vat ?? Infinity) - (b.total_inc_vat ?? Infinity),
        )
      : grouped.primary,
  );
  let primaryIds = $derived(new Set(grouped.primary.map((r) => r.id)));
  let change = $derived(summary?.context.best_change_30d ?? null);
  let enough = $derived(hasEnoughHistory(history, MIN_CHART_DAYS));
  let days = $derived(quoteDayCount(history));
  let prices = $derived(priceSummary(history));
  // Same basis as the price history: the day's best real price per litre.
  let todayBest = $derived(prices.latestBest);
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
    <!-- 1. The answer -->
    <div>
      <OrderCountdown {summary} />
      <p class="mt-2 text-xs text-text-subtle">
        Room for {fixed(summary.headroom_l, 0)} L in the tank.
        {#if change !== null}
          Best price is {change > 0 ? "up" : change < 0 ? "down" : "unchanged"}
          {change !== 0 ? `${Math.abs(change).toFixed(1)}p ` : ""}on 30 days ago.
        {/if}
        {#if summary.updated_at}
          Updated {formatAge(summary.updated_at, now)}.
        {/if}
        <a href="/forecast" class="ml-1 text-brand-blue">See the runway</a>
      </p>
    </div>

    <!-- 2. Quotes -->
    <section>
      <div class="mb-2 flex items-center justify-between">
        <h2 class="text-sm font-semibold text-text">Latest quotes</h2>
        {#if grouped.others.length > 0}
          <button
            type="button"
            class="text-xs text-brand-blue"
            onclick={() => (showAll = !showAll)}
          >
            {showAll ? "Hide other delivery options" : "Show all delivery options"}
          </button>
        {/if}
      </div>
      {#if rows.length === 0}
        <p class="text-sm text-text-muted">No quotes yet.</p>
      {:else}
        <div class="overflow-x-auto rounded-lg border border-border bg-bg-panel">
          <table class="w-full text-left text-sm">
            <thead class="text-[10px] uppercase tracking-wide text-text-label">
              <tr>
                <th class="px-3 py-2">Supplier</th>
                <th class="px-3 py-2 text-right" title="Total divided by litres: VAT, delivery and fees included">Per litre</th>
                <th class="px-3 py-2 text-right" title="Per litre with fees included but VAT removed">Ex VAT</th>
                <th class="px-3 py-2">Delivery</th>
                <th class="px-3 py-2 text-right">Fees</th>
                <th class="px-3 py-2 text-right">Total</th>
                <th class="px-3 py-2">Age</th>
              </tr>
            </thead>
            <tbody>
              {#each rows as r (r.id)}
                <tr
                  class="border-t border-border"
                  class:text-text-subtle={!primaryIds.has(r.id)}
                >
                  <td class="px-3 py-1.5">{supplierName(r.supplier)}</td>
                  {#if r.ok}
                    <td class="px-3 py-1.5 text-right font-mono">{formatPpl(allInPpl(r))}</td>
                    <td class="px-3 py-1.5 text-right font-mono text-text-muted">{formatPpl(r.ppl_effective)}</td>
                    <td class="px-3 py-1.5">
                      {r.delivery_label ?? "n/a"}
                      {#if r.urgent}
                        <span class="ml-1 rounded bg-bg-elev px-1.5 py-0.5 text-[10px] text-brand-amber">
                          faster
                        </span>
                      {/if}
                    </td>
                    <td class="px-3 py-1.5 text-right font-mono">{formatGBP(r.fees_inc_vat ?? 0)}</td>
                    <td class="px-3 py-1.5 text-right font-mono">{formatGBP(r.total_inc_vat)}</td>
                  {:else}
                    <td colspan="5" class="px-3 py-1.5 text-brand-red">
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
          One row per supplier, using its standard delivery. Faster windows cost more.
          Total and Per litre include VAT, delivery and any service fee, and the buy trigger uses Per litre. Ex VAT is the same price without VAT.
        </p>
      {/if}
    </section>

    <!-- 3. Price history -->
    <section>
      <h2 class="mb-2 text-sm font-semibold text-text">Price history</h2>
      {#if enough}
        <PriceHistoryChart quotes={history} trigger={summary.trigger_ppl} />
      {:else}
        <div class="rounded-lg border border-border bg-bg-panel p-4 text-sm text-text-muted">
          <ul class="space-y-1">
            <li>
              Today's best price per litre:
              <span class="font-mono text-text">{formatPpl(todayBest)}</span>
            </li>
            <li>
              National index (VAT added, before supplier fees):
              <span class="font-mono text-text">{formatPpl(prices.latestIndex)}</span>
            </li>
            <li>
              Change since the first quote{prices.firstDate ? ` (${formatDate(prices.firstDate)})` : ""}:
              <span class="font-mono text-text">
                {#if prices.change === null}
                  n/a
                {:else if prices.change === 0}
                  unchanged
                {:else}
                  {prices.change > 0 ? "up" : "down"} {Math.abs(prices.change).toFixed(1)}p
                {/if}
              </span>
            </li>
          </ul>
          <p class="mt-2 text-xs text-text-subtle">
            The chart appears once there are quotes on {MIN_CHART_DAYS} different days
            ({days} so far).
          </p>
        </div>
      {/if}
    </section>
  {/if}
</div>
