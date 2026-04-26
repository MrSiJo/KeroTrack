<script lang="ts">
  import { onMount } from "svelte";
  import HeroShell from "$lib/components/HeroShell.svelte";
  import { api } from "$lib/api";
  import { liveStatus } from "$lib/stores/liveStatus";
  import { bucketMessagesPerMinute } from "$lib/heroes/mqttPulse";

  type Props = { size: "tile" | "full" };
  let { size }: Props = $props();

  let timestamps = $state<number[]>([]);
  let now = $state(Date.now());

  let connected = $derived($liveStatus.health?.mqtt_connected ?? false);
  let topics = $derived<number>(
    Number(($liveStatus.health as { mqtt_topics?: number } | null)?.mqtt_topics ?? 0),
  );
  let lastMs = $derived(timestamps.length ? timestamps[timestamps.length - 1] : null);
  let agoText = $derived(() => {
    if (lastMs == null) return "—";
    const sec = Math.max(0, Math.round((now - lastMs) / 1000));
    if (sec < 60) return `${sec}s`;
    if (sec < 3600) return `${Math.round(sec / 60)} min`;
    return `${Math.round(sec / 3600)} h`;
  });

  let buckets = $derived(bucketMessagesPerMinute(timestamps, now));
  let maxBucket = $derived(buckets.reduce((m, v) => (v > m ? v : m), 0));

  onMount(() => {
    void load();
    const t = setInterval(() => {
      now = Date.now();
      void load();
    }, 30000);
    return () => clearInterval(t);
  });

  async function load() {
    try {
      const resp = await api.mqttFeed(500);
      timestamps = (resp.items ?? []).map((m) => m.ts * 1000);
    } catch {
      // keep last good state
    }
  }
</script>

<HeroShell
  {size}
  accent="emerald"
  label="MQTT"
  range="60m"
  headline={`${connected ? "● Connected" : "○ Off"} · ${agoText()} ago`}
  sub={`${timestamps.length} msgs · ${topics} topic${topics === 1 ? "" : "s"}`}
  href="/mqtt"
>
  <div class={`flex w-full items-end gap-px ${size === "tile" ? "h-[34px]" : "h-[100px]"}`}>
    {#each buckets as count}
      {@const h = maxBucket > 0 ? Math.max(2, (count / maxBucket) * 100) : 2}
      <div class="flex-1 bg-brand-emerald" style={`height: ${h}%; opacity: ${count > 0 ? 0.4 + (count / Math.max(1, maxBucket)) * 0.5 : 0.15};`}></div>
    {/each}
  </div>
</HeroShell>
