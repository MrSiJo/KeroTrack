<script lang="ts">
  import { onMount } from "svelte";

  import { api } from "$lib/api";
  import { daysUntil, isoToday, stateLabel } from "$lib/buying";
  import {
    activeScenario,
    formatDate,
    formatShortDate,
    scenarioRangeText,
    settingNumber,
    stateSentence,
    stateToneClass,
    timelineGeometry,
  } from "$lib/countdown";
  import { settings } from "$lib/stores/settings";
  import type { BuyingSummary } from "$lib/types/api";

  type Props = {
    /** Pass a summary the page already holds; otherwise the card loads its own. */
    summary?: BuyingSummary | null;
    /** The parent's summary fetch failed. */
    failed?: boolean;
    /** Make the whole card a link to /buying (dashboard). */
    linkToBuying?: boolean;
  };

  let { summary = undefined, failed: parentFailed = false, linkToBuying = false }: Props =
    $props();

  let own = $state<BuyingSummary | null>(null);
  let failed = $state(false);
  let today = $state(isoToday());

  onMount(async () => {
    today = isoToday();
    if (summary !== undefined) return;
    try {
      own = await api.getBuyingSummary();
    } catch {
      failed = true;
    }
  });

  let data = $derived(summary !== undefined ? summary : own);
  let unavailable = $derived(failed || parentFailed);
  let scenario = $derived(activeScenario(data));
  let orderBy = $derived(scenario?.order_by ?? null);
  let runOut = $derived(scenario?.run_out ?? null);
  let days = $derived(daysUntil(orderBy, today));
  let minOrderL = $derived(settingNumber($settings.items, "buying.min_order_litres", 500));
  let sentence = $derived(
    data ? stateSentence(data.state, data, { minOrderL, today }) : "",
  );
  let geo = $derived(timelineGeometry(today, orderBy, runOut));
  let range = $derived(scenarioRangeText(data?.scenarios));

  function daysText(n: number | null): string {
    if (n === null) return "";
    if (n === 0) return "today";
    const abs = Math.abs(n);
    const unit = abs === 1 ? "day" : "days";
    return n > 0 ? `${abs} ${unit}` : `${abs} ${unit} ago`;
  }

  const barTone: Record<string, string> = {
    buy_now: "bg-brand-emerald",
    deadline: "bg-brand-amber",
    overdue: "bg-brand-red",
    wait: "bg-brand-blue",
  };
</script>

{#snippet body(d: BuyingSummary)}
  <div class="flex flex-wrap items-center justify-between gap-2">
    <div class="font-mono text-base font-semibold uppercase tracking-wide text-text md:text-lg">
      {#if orderBy}
        Order by {formatDate(orderBy)}
        <span class="text-text-muted">·</span>
        <span class="normal-case">{daysText(days)}</span>
      {:else}
        No order by date yet
      {/if}
    </div>
    <span
      class={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${stateToneClass(d.state)}`}
    >
      {stateLabel(d.state)}
    </span>
  </div>

  <p class="mt-1 text-sm text-text-muted">{sentence}</p>

  {#if geo}
    <div class="mt-6 mb-6 px-1">
      <div class="relative h-2 rounded-full bg-bg-elev">
        {#if geo.orderPct !== null}
          <div
            class={`absolute left-0 top-0 h-2 rounded-full opacity-60 ${barTone[d.state] ?? "bg-border-strong"}`}
            style="width: {geo.orderPct}%;"
            title="Buy window"
          ></div>
          <div
            class="absolute -top-1 h-4 w-0.5 bg-text"
            style="left: {geo.orderPct}%;"
          ></div>
          <div
            class="absolute -top-5 -translate-x-1/2 whitespace-nowrap text-[10px] text-text"
            style="left: clamp(2.5rem, {geo.orderPct}%, calc(100% - 2.5rem));"
          >
            Order by {formatShortDate(orderBy)}
          </div>
        {/if}
        {#if geo.runOutPct !== null}
          <div
            class="absolute -top-1 h-4 w-0.5 bg-brand-red"
            style="left: {geo.runOutPct}%;"
          ></div>
          <div
            class="absolute top-3 -translate-x-1/2 whitespace-nowrap text-[10px] text-brand-red"
            style="left: clamp(2.5rem, {geo.runOutPct}%, calc(100% - 2.5rem));"
          >
            Reserve {formatShortDate(runOut)}
          </div>
        {/if}
        <div class="absolute left-0 top-3 text-[10px] text-text-subtle">Today</div>
      </div>
    </div>
  {/if}

  {#if range}
    <p class="text-xs text-text-subtle">{range}</p>
  {/if}
{/snippet}

{#if unavailable && !data}
  <p class="rounded-lg border border-border bg-bg-panel px-4 py-2 text-sm text-text-muted">
    Order date unavailable.
  </p>
{:else if linkToBuying}
  <a
    href="/buying"
    class={`block rounded-lg border-2 bg-bg-panel p-4 transition hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue focus-visible:ring-offset-2 focus-visible:ring-offset-bg-page ${stateToneClass(data?.state)}`}
  >
    {#if data}{@render body(data)}{:else}<span class="text-sm text-text-muted">Loading order countdown...</span>{/if}
  </a>
{:else}
  <section class={`rounded-lg border-2 bg-bg-panel p-4 ${stateToneClass(data?.state)}`}>
    {#if data}{@render body(data)}{:else}<span class="text-sm text-text-muted">Loading order countdown...</span>{/if}
  </section>
{/if}
