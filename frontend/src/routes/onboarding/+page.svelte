<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";

  import { api, ApiError } from "$lib/api";
  import { settings } from "$lib/stores/settings";
  import { get } from "svelte/store";

  let step = $state(1);
  let saving = $state(false);
  let error = $state<string | null>(null);

  // Step 1 — MQTT
  let mqttBroker = $state("localhost");
  let mqttPort = $state(1883);
  let mqttUsername = $state("");
  let mqttPassword = $state("");
  let mqttTopicReadings = $state("oiltank/readings");
  let mqttTopicAnalytics = $state("oiltank/analytics");

  // Step 2 — Tank
  let tankCapacity = $state(1225);
  let tankLength = $state(178.5);
  let tankWidth = $state(75);
  let tankHeight = $state(137);

  // Step 3 — Boiler (all optional)
  let boilerModel = $state("");
  let boilerBurner = $state("");
  let boilerNozzle = $state(0.6);
  let boilerInputKw = $state(22.1);
  let boilerOutputKw = $state(21.5);
  let boilerEfficiency = $state(99);

  // Pre-fill from current settings if any are already non-default
  onMount(async () => {
    await settings.refresh();
    const snapshot = get(settings);
    const get_ = (k: string) => snapshot.items.find((i) => i.key === k)?.value;

    const b = get_("mqtt.broker");
    if (b && b !== "localhost") mqttBroker = String(b);
    const p = get_("mqtt.port");
    if (typeof p === "number") mqttPort = p;
    const u = get_("mqtt.username");
    if (u) mqttUsername = String(u);
    const tr = get_("mqtt.topic_readings");
    if (tr) mqttTopicReadings = String(tr);
    const ta = get_("mqtt.topic_analytics");
    if (ta) mqttTopicAnalytics = String(ta);

    const cap = get_("tank.capacity_l");
    if (typeof cap === "number") tankCapacity = cap;
    const len = get_("tank.length_cm");
    if (typeof len === "number") tankLength = len;
    const wid = get_("tank.width_cm");
    if (typeof wid === "number") tankWidth = wid;
    const hei = get_("tank.height_cm");
    if (typeof hei === "number") tankHeight = hei;

    const bm = get_("boiler.model");
    if (bm) boilerModel = String(bm);
    const bb = get_("boiler.burner");
    if (bb) boilerBurner = String(bb);
    const bn = get_("boiler.nozzle");
    if (typeof bn === "number") boilerNozzle = bn;
    const bi = get_("boiler.input_kw");
    if (typeof bi === "number") boilerInputKw = bi;
    const bo = get_("boiler.output_kw");
    if (typeof bo === "number") boilerOutputKw = bo;
    const be = get_("boiler.efficiency_pct");
    if (typeof be === "number") boilerEfficiency = be;
  });

  function next() {
    if (step < 3) step += 1;
  }
  function back() {
    if (step > 1) step -= 1;
  }

  function dismiss() {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("kerotrack.onboarding.dismissed", "1");
    }
    void goto("/");
  }

  async function finish() {
    saving = true;
    error = null;
    const diff: Record<string, unknown> = {
      "mqtt.broker": mqttBroker,
      "mqtt.port": mqttPort,
      "mqtt.username": mqttUsername,
      "mqtt.topic_readings": mqttTopicReadings,
      "mqtt.topic_analytics": mqttTopicAnalytics,
      "tank.capacity_l": tankCapacity,
      "tank.length_cm": tankLength,
      "tank.width_cm": tankWidth,
      "tank.height_cm": tankHeight,
      "boiler.model": boilerModel,
      "boiler.burner": boilerBurner,
      "boiler.nozzle": boilerNozzle,
      "boiler.input_kw": boilerInputKw,
      "boiler.output_kw": boilerOutputKw,
      "boiler.efficiency_pct": boilerEfficiency,
    };
    if (mqttPassword) diff["mqtt.password"] = mqttPassword;
    try {
      await api.bulkSetSettings(diff);
      if (typeof localStorage !== "undefined") {
        localStorage.setItem("kerotrack.onboarding.dismissed", "1");
      }
      void goto("/");
    } catch (err) {
      error = err instanceof ApiError ? err.message : (err as Error).message;
    } finally {
      saving = false;
    }
  }
</script>

<div class="mx-auto flex min-h-screen max-w-2xl flex-col items-stretch justify-center p-6">
  <div class="rounded-lg border border-border bg-bg-panel p-6">
    <header class="flex items-center justify-between">
      <div>
        <h1 class="text-lg font-semibold text-text">Welcome to KeroTrack</h1>
        <p class="text-xs text-text-subtle">A few things to set up before you start tracking. Step {step} of 3.</p>
      </div>
      <button
        type="button"
        class="text-[11px] text-text-subtle hover:text-text"
        onclick={dismiss}
      >
        Skip — I'll set this up later
      </button>
    </header>

    <div class="mt-4 flex items-center gap-2">
      {#each [1, 2, 3] as s}
        <div class={`h-1 flex-1 rounded ${s <= step ? "bg-brand-blue" : "bg-border"}`}></div>
      {/each}
    </div>

    {#if error}
      <p class="mt-4 text-xs text-brand-red">{error}</p>
    {/if}

    {#if step === 1}
      <section class="mt-6 space-y-3">
        <h2 class="text-sm font-medium text-text">MQTT broker</h2>
        <p class="text-[11px] text-text-subtle">Where readings come from. The Watchman sensor publishes here; KeroTrack subscribes.</p>
        <label class="block">
          <span class="text-[11px] text-text-muted">Host</span>
          <input class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={mqttBroker} placeholder="e.g. 192.168.1.10" />
        </label>
        <div class="grid grid-cols-2 gap-3">
          <label class="block">
            <span class="text-[11px] text-text-muted">Port</span>
            <input type="number" class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={mqttPort} />
          </label>
          <label class="block">
            <span class="text-[11px] text-text-muted">Username</span>
            <input class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={mqttUsername} />
          </label>
        </div>
        <label class="block">
          <span class="text-[11px] text-text-muted">Password (leave blank if unauthenticated)</span>
          <input type="password" class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={mqttPassword} autocomplete="new-password" />
        </label>
        <div class="grid grid-cols-2 gap-3">
          <label class="block">
            <span class="text-[11px] text-text-muted">Readings topic</span>
            <input class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={mqttTopicReadings} />
          </label>
          <label class="block">
            <span class="text-[11px] text-text-muted">Analytics topic</span>
            <input class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={mqttTopicAnalytics} />
          </label>
        </div>
      </section>
    {:else if step === 2}
      <section class="mt-6 space-y-3">
        <h2 class="text-sm font-medium text-text">Tank dimensions</h2>
        <p class="text-[11px] text-text-subtle">Your tank's capacity and physical size. Used for level calculations and the silhouette on the dashboard. Defaults match a standard 1225 L domestic tank — adjust if yours is different.</p>
        <div class="grid grid-cols-2 gap-3">
          <label class="block">
            <span class="text-[11px] text-text-muted">Capacity (L)</span>
            <input type="number" class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={tankCapacity} />
          </label>
          <label class="block">
            <span class="text-[11px] text-text-muted">Length (cm)</span>
            <input type="number" step="0.1" class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={tankLength} />
          </label>
          <label class="block">
            <span class="text-[11px] text-text-muted">Width (cm)</span>
            <input type="number" step="0.1" class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={tankWidth} />
          </label>
          <label class="block">
            <span class="text-[11px] text-text-muted">Height (cm)</span>
            <input type="number" step="0.1" class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={tankHeight} />
          </label>
        </div>
      </section>
    {:else}
      <section class="mt-6 space-y-3">
        <h2 class="text-sm font-medium text-text">Boiler (optional)</h2>
        <p class="text-[11px] text-text-subtle">Used for cost analysis and consumption modelling. Defaults are reasonable averages — fill in what you know, leave the rest.</p>
        <div class="grid grid-cols-2 gap-3">
          <label class="block">
            <span class="text-[11px] text-text-muted">Model</span>
            <input class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={boilerModel} placeholder="e.g. Worcester Greenstar" />
          </label>
          <label class="block">
            <span class="text-[11px] text-text-muted">Burner</span>
            <input class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={boilerBurner} />
          </label>
          <label class="block">
            <span class="text-[11px] text-text-muted">Nozzle (gph)</span>
            <input type="number" step="0.01" class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={boilerNozzle} />
          </label>
          <label class="block">
            <span class="text-[11px] text-text-muted">Efficiency %</span>
            <input type="number" step="0.1" class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={boilerEfficiency} />
          </label>
          <label class="block">
            <span class="text-[11px] text-text-muted">Input (kW)</span>
            <input type="number" step="0.1" class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={boilerInputKw} />
          </label>
          <label class="block">
            <span class="text-[11px] text-text-muted">Output (kW)</span>
            <input type="number" step="0.1" class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={boilerOutputKw} />
          </label>
        </div>
      </section>
    {/if}

    <footer class="mt-6 flex items-center justify-between">
      <button
        type="button"
        class="rounded border border-border px-3 py-1.5 text-xs text-text-muted hover:border-border-strong hover:text-text disabled:opacity-50"
        onclick={back}
        disabled={step === 1}
      >
        ← Back
      </button>
      {#if step < 3}
        <button
          type="button"
          class="rounded bg-brand-blue px-4 py-1.5 text-xs font-medium text-white"
          onclick={next}
        >
          Next →
        </button>
      {:else}
        <button
          type="button"
          class="rounded bg-brand-blue px-4 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          onclick={finish}
          disabled={saving}
        >
          {saving ? "Saving…" : "Save & finish"}
        </button>
      {/if}
    </footer>
  </div>
</div>
