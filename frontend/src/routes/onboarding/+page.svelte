<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";

  import { api, ApiError } from "$lib/api";
  import { settings } from "$lib/stores/settings";
  import { get } from "svelte/store";

  let step = $state(1);
  let saving = $state(false);
  let loaded = $state(false);
  let error = $state<string | null>(null);

  // Pre-filled from the live settings snapshot in onMount so the wizard
  // never drifts from the catalogue defaults in backend/.../schema.py.
  // Initial values are placeholders only and never reach the API — Save
  // is gated on `loaded`.
  let mqttBroker = $state("");
  let mqttPort = $state(1883);
  let mqttUsername = $state("");
  let mqttPassword = $state("");
  let mqttTopicReadings = $state("");
  let mqttTopicReadingsPublish = $state("");
  let mqttTopicAnalytics = $state("");
  let mqttTopicCostanalysis = $state("");

  let tankCapacity = $state(0);
  let tankLength = $state(0);
  let tankWidth = $state(0);
  let tankHeight = $state(0);

  let boilerModel = $state("");
  let boilerBurner = $state("");
  let boilerNozzle = $state(0);
  let boilerInputKw = $state(0);
  let boilerOutputKw = $state(0);
  let boilerEfficiency = $state(0);

  // Snapshot of values at load time, used to send only changed keys.
  let initial: Record<string, unknown> = {};

  onMount(async () => {
    await settings.refresh();
    const snapshot = get(settings);
    const lookup = (k: string) =>
      snapshot.items.find((i) => i.key === k)?.value;
    const str = (k: string, fallback = "") => {
      const v = lookup(k);
      return v == null ? fallback : String(v);
    };
    const num = (k: string, fallback = 0) => {
      const v = lookup(k);
      return typeof v === "number" ? v : fallback;
    };

    mqttBroker = str("mqtt.broker", "localhost");
    mqttPort = num("mqtt.port", 1883);
    mqttUsername = str("mqtt.username");
    mqttTopicReadings = str("mqtt.topic_readings");
    mqttTopicReadingsPublish = str("mqtt.topic_readings_publish");
    mqttTopicAnalytics = str("mqtt.topic_analytics");
    mqttTopicCostanalysis = str("mqtt.topic_costanalysis");

    tankCapacity = num("tank.capacity_l");
    tankLength = num("tank.length_cm");
    tankWidth = num("tank.width_cm");
    tankHeight = num("tank.height_cm");

    boilerModel = str("boiler.model");
    boilerBurner = str("boiler.burner");
    boilerNozzle = num("boiler.nozzle");
    boilerInputKw = num("boiler.input_kw");
    boilerOutputKw = num("boiler.output_kw");
    boilerEfficiency = num("boiler.efficiency_pct");

    initial = {
      "mqtt.broker": mqttBroker,
      "mqtt.port": mqttPort,
      "mqtt.username": mqttUsername,
      "mqtt.topic_readings": mqttTopicReadings,
      "mqtt.topic_readings_publish": mqttTopicReadingsPublish,
      "mqtt.topic_analytics": mqttTopicAnalytics,
      "mqtt.topic_costanalysis": mqttTopicCostanalysis,
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
    loaded = true;
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
    const current: Record<string, unknown> = {
      "mqtt.broker": mqttBroker,
      "mqtt.port": mqttPort,
      "mqtt.username": mqttUsername,
      "mqtt.topic_readings": mqttTopicReadings,
      "mqtt.topic_readings_publish": mqttTopicReadingsPublish,
      "mqtt.topic_analytics": mqttTopicAnalytics,
      "mqtt.topic_costanalysis": mqttTopicCostanalysis,
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
    const diff: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(current)) {
      if (value !== initial[key]) diff[key] = value;
    }
    if (mqttPassword) diff["mqtt.password"] = mqttPassword;
    try {
      if (Object.keys(diff).length > 0) {
        await api.bulkSetSettings(diff);
      }
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
          <input class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text" bind:value={mqttBroker} placeholder="e.g. mqtt.lan" />
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
        <label class="block">
          <span class="text-[11px] text-text-muted">Readings topic (subscribe — what the LilyGO publishes to)</span>
          <input class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm font-mono text-text" bind:value={mqttTopicReadings} placeholder="lilygo/+/RTL_433toMQTT/Oil-SonicAdv/+" />
          <span class="mt-1 block text-[10px] text-text-subtle">Default matches the standard LilyGO LoRa32 + OpenMQTTGateway shape. <code>+</code> wildcards each path level so the device hostname and Watchman ID don't matter.</span>
        </label>

        <details class="rounded border border-border bg-bg-elev/50 px-3 py-2">
          <summary class="cursor-pointer text-[11px] text-text-muted hover:text-text">Advanced — output topics</summary>
          <div class="mt-3 space-y-3">
            <p class="text-[10px] text-text-subtle">KeroTrack publishes the enriched reading + analytics + cost figures back to MQTT under these topics. Defaults are KeroDisplay/Home-Assistant compatible — only change them if you need to namespace your broker.</p>
            <label class="block">
              <span class="text-[11px] text-text-muted">Level topic (publish)</span>
              <input class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm font-mono text-text" bind:value={mqttTopicReadingsPublish} />
            </label>
            <label class="block">
              <span class="text-[11px] text-text-muted">Analysis topic (publish)</span>
              <input class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm font-mono text-text" bind:value={mqttTopicAnalytics} />
            </label>
            <label class="block">
              <span class="text-[11px] text-text-muted">Cost analysis topic (publish)</span>
              <input class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm font-mono text-text" bind:value={mqttTopicCostanalysis} />
            </label>
          </div>
        </details>
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
          disabled={saving || !loaded}
        >
          {saving ? "Saving…" : !loaded ? "Loading…" : "Save & finish"}
        </button>
      {/if}
    </footer>
  </div>
</div>
