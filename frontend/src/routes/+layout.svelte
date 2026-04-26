<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";

  import "../app.css";

  import KeyboardHints from "$lib/components/KeyboardHints.svelte";
  import Sidebar from "$lib/components/Sidebar.svelte";
  import ThemeToggle from "$lib/components/ThemeToggle.svelte";
  import { registerKeroTrackTheme } from "$lib/charts/theme";
  import { get } from "svelte/store";

  import { auth } from "$lib/stores/auth";
  import { liveStatus } from "$lib/stores/liveStatus";
  import { settings } from "$lib/stores/settings";

  let { children } = $props();

  onMount(() => {
    registerKeroTrackTheme();
    void auth.refresh();
  });

  $effect(() => {
    const path = page.url.pathname;
    if ($auth.loading) return;
    if ($auth.needsSetup) {
      if (path !== "/setup") goto("/setup");
      return;
    }
    if (!$auth.user) {
      if (path !== "/login" && path !== "/setup") goto("/login");
      return;
    }
    // Authenticated — boot live status + SSE.
    void liveStatus.refresh();
    liveStatus.start();

    // Onboarding gate — redirect once if user hasn't configured the basics.
    if (path === "/onboarding") return;
    if (typeof localStorage !== "undefined" && localStorage.getItem("kerotrack.onboarding.dismissed") === "1") return;
    void settings.refresh().then(() => {
      const snapshot = get(settings);
      const items = snapshot.items;
      if (!items.length) return;
      const broker = items.find((i) => i.key === "mqtt.broker")?.value;
      const username = items.find((i) => i.key === "mqtt.username")?.value;
      const apprise = items.find((i) => i.key === "notifications.apprise_urls")?.value;
      const appriseEmpty = !Array.isArray(apprise) || apprise.length === 0;
      if (broker === "localhost" && (!username || username === "") && appriseEmpty) {
        void goto("/onboarding");
      }
    });
  });
</script>

<svelte:head>
  <title>KeroTrack v2</title>
  <link
    rel="preconnect"
    href="https://rsms.me/"
  />
  <link
    rel="stylesheet"
    href="https://rsms.me/inter/inter.css"
  />
</svelte:head>

<KeyboardHints />

{#if $auth.loading || $auth.needsSetup === null}
  <div class="grid h-screen place-items-center text-text-muted">Loading…</div>
{:else if $auth.needsSetup || !$auth.user}
  <div class="grid min-h-screen place-items-center bg-bg-page">
    {@render children?.()}
  </div>
{:else}
  <div class="flex min-h-screen bg-bg-page">
    <Sidebar />
    <div class="flex flex-1 flex-col">
      <header
        class="flex items-center justify-between border-b border-border px-6 py-3"
      >
        <div class="text-sm text-text-muted">
          {page.url.pathname === "/" ? "Dashboard" : page.url.pathname.slice(1)}
        </div>
        <div class="flex items-center gap-3">
          {#if $liveStatus.health}
            <span
              class="rounded px-2 py-0.5 text-xs"
              class:bg-emerald-900={$liveStatus.health.db === "ok"}
              class:text-brand-emerald={$liveStatus.health.db === "ok"}
              class:bg-red-900={$liveStatus.health.db === "down"}
              class:text-brand-red={$liveStatus.health.db === "down"}
            >
              db: {$liveStatus.health.db}
            </span>
            <span
              class="rounded px-2 py-0.5 text-xs"
              class:bg-emerald-900={$liveStatus.health.mqtt_connected}
              class:text-brand-emerald={$liveStatus.health.mqtt_connected}
              class:bg-amber-900={!$liveStatus.health.mqtt_connected}
              class:text-brand-amber={!$liveStatus.health.mqtt_connected}
            >
              mqtt: {$liveStatus.health.mqtt_connected ? "connected" : "off"}
            </span>
          {/if}
          <ThemeToggle />
        </div>
      </header>
      <main class="flex-1 px-6 py-6">
        {@render children?.()}
      </main>
    </div>
  </div>
{/if}
