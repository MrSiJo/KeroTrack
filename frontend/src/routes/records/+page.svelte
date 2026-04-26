<script lang="ts">
  import { onMount } from "svelte";

  import HeroRecords from "$lib/components/HeroRecords.svelte";
  import { api } from "$lib/api";
  import type { Reading } from "$lib/types/api";

  type TriState = "any" | "y" | "n";

  let items = $state<Reading[]>([]);
  let total = $state(0);
  let limit = $state(100);
  let offset = $state(0);
  let loading = $state(false);
  let error = $state<string | null>(null);

  // Server-side filters
  let sinceLocal = $state("");
  let untilLocal = $state("");

  // Client-side filters
  let litresMin = $state<string>("");
  let litresMax = $state<string>("");
  let pctMin = $state<string>("");
  let pctMax = $state<string>("");
  let usedMin = $state<string>("");
  let usedMax = $state<string>("");
  let tempMin = $state<string>("");
  let tempMax = $state<string>("");
  let refillFilter = $state<TriState>("any");
  let leakFilter = $state<TriState>("any");

  function localToApi(v: string): string | undefined {
    // datetime-local gives "YYYY-MM-DDTHH:MM" in user's local zone.
    // The API accepts "YYYY-MM-DD HH:MM:SS" strings (ambiguous about
    // timezone). Convert by replacing T with space and appending :00.
    if (!v) return undefined;
    const cleaned = v.replace("T", " ");
    return cleaned.length === 16 ? `${cleaned}:00` : cleaned;
  }

  async function refresh() {
    loading = true;
    error = null;
    try {
      const resp = await api.readings({
        limit,
        offset,
        order: "desc",
        since: localToApi(sinceLocal),
        until: localToApi(untilLocal),
      });
      items = resp.items;
      total = resp.total;
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  onMount(refresh);

  function next() {
    if (offset + limit < total) {
      offset = offset + limit;
      void refresh();
    }
  }
  function prev() {
    if (offset > 0) {
      offset = Math.max(0, offset - limit);
      void refresh();
    }
  }

  async function del(date: string) {
    if (!confirm(`Delete reading at ${date}?`)) return;
    await api.deleteReading(date);
    await refresh();
  }

  function applyServerFilters() {
    offset = 0;
    void refresh();
  }

  function clearFilters() {
    sinceLocal = "";
    untilLocal = "";
    litresMin = "";
    litresMax = "";
    pctMin = "";
    pctMax = "";
    usedMin = "";
    usedMax = "";
    tempMin = "";
    tempMax = "";
    refillFilter = "any";
    leakFilter = "any";
    offset = 0;
    void refresh();
  }

  function num(s: string): number | null {
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }

  function inRange(v: number | null | undefined, lo: number | null, hi: number | null): boolean {
    if (v == null) return lo == null && hi == null;
    if (lo != null && v < lo) return false;
    if (hi != null && v > hi) return false;
    return true;
  }

  let displayed = $derived(() => {
    const lMin = num(litresMin);
    const lMax = num(litresMax);
    const pMin = num(pctMin);
    const pMax = num(pctMax);
    const uMin = num(usedMin);
    const uMax = num(usedMax);
    const tMin = num(tempMin);
    const tMax = num(tempMax);
    return items.filter((r) => {
      if (!inRange(r.litres_remaining ?? null, lMin, lMax)) return false;
      if (!inRange(r.percentage_remaining ?? null, pMin, pMax)) return false;
      if (!inRange(r.litres_used_since_last ?? null, uMin, uMax)) return false;
      if (!inRange(r.temperature ?? null, tMin, tMax)) return false;
      if (refillFilter !== "any" && (r.refill_detected ?? "n") !== refillFilter) return false;
      if (leakFilter !== "any" && (r.leak_detected ?? "n") !== leakFilter) return false;
      return true;
    });
  });

  let clientFiltersActive = $derived(
    !!(litresMin || litresMax || pctMin || pctMax || usedMin || usedMax || tempMin || tempMax) ||
      refillFilter !== "any" ||
      leakFilter !== "any",
  );
</script>

<div class="space-y-6">
  <HeroRecords size="full" />

  <section class="rounded-lg border border-border bg-bg-panel p-3">
    <div class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
      <label class="flex flex-col gap-1 text-[11px] text-text-muted">
        From
        <input
          type="datetime-local"
          class="rounded border border-border bg-bg-elev px-2 py-1 text-xs text-text"
          bind:value={sinceLocal}
          onchange={applyServerFilters}
        />
      </label>
      <label class="flex flex-col gap-1 text-[11px] text-text-muted">
        To
        <input
          type="datetime-local"
          class="rounded border border-border bg-bg-elev px-2 py-1 text-xs text-text"
          bind:value={untilLocal}
          onchange={applyServerFilters}
        />
      </label>
      <div class="flex flex-col gap-1 text-[11px] text-text-muted">
        Litres
        <div class="flex gap-1">
          <input type="number" placeholder="min" class="w-full rounded border border-border bg-bg-elev px-2 py-1 text-xs text-text" bind:value={litresMin} />
          <input type="number" placeholder="max" class="w-full rounded border border-border bg-bg-elev px-2 py-1 text-xs text-text" bind:value={litresMax} />
        </div>
      </div>
      <div class="flex flex-col gap-1 text-[11px] text-text-muted">
        %
        <div class="flex gap-1">
          <input type="number" placeholder="min" class="w-full rounded border border-border bg-bg-elev px-2 py-1 text-xs text-text" bind:value={pctMin} />
          <input type="number" placeholder="max" class="w-full rounded border border-border bg-bg-elev px-2 py-1 text-xs text-text" bind:value={pctMax} />
        </div>
      </div>
      <div class="flex flex-col gap-1 text-[11px] text-text-muted">
        Used
        <div class="flex gap-1">
          <input type="number" placeholder="min" class="w-full rounded border border-border bg-bg-elev px-2 py-1 text-xs text-text" bind:value={usedMin} />
          <input type="number" placeholder="max" class="w-full rounded border border-border bg-bg-elev px-2 py-1 text-xs text-text" bind:value={usedMax} />
        </div>
      </div>
      <div class="flex flex-col gap-1 text-[11px] text-text-muted">
        Temp °C
        <div class="flex gap-1">
          <input type="number" placeholder="min" class="w-full rounded border border-border bg-bg-elev px-2 py-1 text-xs text-text" bind:value={tempMin} />
          <input type="number" placeholder="max" class="w-full rounded border border-border bg-bg-elev px-2 py-1 text-xs text-text" bind:value={tempMax} />
        </div>
      </div>
      <fieldset class="flex flex-col gap-1 text-[11px] text-text-muted">
        Refill
        <div class="flex items-center gap-3 text-xs text-text">
          <label class="flex items-center gap-1"><input type="radio" bind:group={refillFilter} value="any" /> any</label>
          <label class="flex items-center gap-1"><input type="radio" bind:group={refillFilter} value="y" /> yes</label>
          <label class="flex items-center gap-1"><input type="radio" bind:group={refillFilter} value="n" /> no</label>
        </div>
      </fieldset>
      <fieldset class="flex flex-col gap-1 text-[11px] text-text-muted">
        Leak
        <div class="flex items-center gap-3 text-xs text-text">
          <label class="flex items-center gap-1"><input type="radio" bind:group={leakFilter} value="any" /> any</label>
          <label class="flex items-center gap-1"><input type="radio" bind:group={leakFilter} value="y" /> yes</label>
          <label class="flex items-center gap-1"><input type="radio" bind:group={leakFilter} value="n" /> no</label>
        </div>
      </fieldset>
    </div>
    <div class="mt-3 flex items-center justify-between">
      <span class="text-[11px] text-text-subtle">
        {#if clientFiltersActive}
          Showing {displayed().length} of {items.length} loaded · {total} total
        {:else}
          {total} total · showing {Math.min(items.length, limit)} on this page
        {/if}
      </span>
      <button
        type="button"
        class="rounded border border-border px-2 py-1 text-[11px] text-text-muted hover:border-border-strong hover:text-text"
        onclick={clearFilters}
      >
        Clear filters
      </button>
    </div>
  </section>

  <div class="rounded-lg border border-border bg-bg-panel">
    <header class="flex items-center justify-between border-b border-border px-4 py-3">
      <h2 class="text-sm font-semibold">Readings</h2>
      <div class="text-xs text-text-muted tabular-nums">
        {#if clientFiltersActive}
          {displayed().length} match{displayed().length === 1 ? "" : "es"} of {items.length} loaded
        {:else}
          {total} rows · showing {offset + 1}–{Math.min(offset + limit, total)}
        {/if}
      </div>
    </header>

    {#if error}
      <p class="px-4 py-3 text-xs text-brand-red">{error}</p>
    {/if}

    <div class="overflow-x-auto">
      <table class="w-full text-sm tabular">
        <thead class="bg-bg-elev text-xs text-text-label">
          <tr>
            <th class="px-3 py-2 text-left">Date</th>
            <th class="px-3 py-2 text-right">Litres</th>
            <th class="px-3 py-2 text-right">%</th>
            <th class="px-3 py-2 text-right">Used</th>
            <th class="px-3 py-2 text-right">Temp</th>
            <th class="px-3 py-2 text-left">Refill</th>
            <th class="px-3 py-2 text-left">Leak</th>
            <th class="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {#each displayed() as row (row.date + row.id)}
            <tr class="border-t border-border">
              <td class="px-3 py-1.5 font-mono text-xs">{row.date}</td>
              <td class="px-3 py-1.5 text-right font-mono">{row.litres_remaining?.toFixed(1) ?? "—"}</td>
              <td class="px-3 py-1.5 text-right font-mono">{row.percentage_remaining?.toFixed(1) ?? "—"}</td>
              <td class="px-3 py-1.5 text-right font-mono">{row.litres_used_since_last?.toFixed(1) ?? "—"}</td>
              <td class="px-3 py-1.5 text-right font-mono">{row.temperature?.toFixed(1) ?? "—"}</td>
              <td class="px-3 py-1.5">{#if row.refill_detected === "y"}<span class="text-brand-emerald">y</span>{:else}n{/if}</td>
              <td class="px-3 py-1.5">{#if row.leak_detected === "y"}<span class="text-brand-red">y</span>{:else}n{/if}</td>
              <td class="px-3 py-1.5 text-right">
                <button class="text-xs text-text-subtle hover:text-brand-red" onclick={() => del(row.date)}>delete</button>
              </td>
            </tr>
          {/each}
          {#if !displayed().length && !loading}
            <tr>
              <td class="px-3 py-6 text-center text-text-subtle" colspan="8">
                {clientFiltersActive ? "No rows match the current filters" : "No readings yet"}
              </td>
            </tr>
          {/if}
        </tbody>
      </table>
    </div>

    <footer class="flex items-center justify-end gap-2 border-t border-border px-4 py-3 text-xs">
      <button
        class="rounded border border-border px-2 py-1 disabled:opacity-50"
        onclick={prev}
        disabled={offset === 0 || loading}>← prev</button
      >
      <button
        class="rounded border border-border px-2 py-1 disabled:opacity-50"
        onclick={next}
        disabled={offset + limit >= total || loading}>next →</button
      >
    </footer>
  </div>
</div>
