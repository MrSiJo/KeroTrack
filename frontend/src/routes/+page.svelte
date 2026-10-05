<script lang="ts">
  import { onMount } from "svelte";

  import { api } from "$lib/api";
  import HeroCosts from "$lib/components/HeroCosts.svelte";
  import HeroForecast from "$lib/components/HeroForecast.svelte";
  import HeroMqtt from "$lib/components/HeroMqtt.svelte";
  import HeroRecords from "$lib/components/HeroRecords.svelte";
  import HeroTrends from "$lib/components/HeroTrends.svelte";
  import OrderCountdown from "$lib/components/OrderCountdown.svelte";
  import TankHeroPanel from "$lib/components/TankHeroPanel.svelte";
  import { liveStatus } from "$lib/stores/liveStatus";
  import { settings } from "$lib/stores/settings";
  import type { BuyingSummary } from "$lib/types/api";

  // One runway fetch for the whole dashboard, shared by the cards below.
  let summary = $state<BuyingSummary | null>(null);
  let summaryFailed = $state(false);

  onMount(() => {
    void liveStatus.refresh();
    void settings.refresh();
    api
      .getBuyingSummary()
      .then((s) => (summary = s))
      .catch(() => (summaryFailed = true));
  });

  let reading = $derived($liveStatus.status?.reading);
</script>

<div class="grid grid-cols-12 gap-4">
  <div class="col-span-12"><OrderCountdown {summary} failed={summaryFailed} linkToBuying /></div>
  <section class="col-span-12 lg:col-span-5">
    <TankHeroPanel {summary} {summaryFailed} />
  </section>

  <section class="col-span-12 lg:col-span-7">
    <div class="grid grid-cols-2 gap-3">
      <HeroTrends size="tile" />
      <HeroForecast size="tile" {summary} />
      <HeroCosts size="tile" />
      <HeroRecords size="tile" />
      <div class="col-span-2"><HeroMqtt size="tile" /></div>
    </div>
  </section>

  {#if reading == null}
    <p class="col-span-12 text-sm text-text-muted">
      No readings yet. Point <code class="font-mono">mqtt.broker</code> at your real
      broker via Settings, or run the Phase 6 migrator to import a v1 snapshot.
    </p>
  {/if}
</div>
