<script lang="ts">
  import { onMount } from "svelte";
  import HeroShell from "$lib/components/HeroShell.svelte";
  import { api } from "$lib/api";
  import type { Reading } from "$lib/types/api";
  import { buildTimelineEvents } from "$lib/heroes/timeline";

  type Props = { size: "tile" | "full" };
  let { size }: Props = $props();

  let readings = $state<Reading[]>([]);

  function isoDaysAgo(days: number): string {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - days);
    return d.toISOString().slice(0, 10);
  }

  onMount(async () => {
    try {
      const resp = await api.readings({
        since: `${isoDaysAgo(30)} 00:00:00`,
        order: "asc",
        limit: 2000,
      });
      readings = resp.items ?? [];
    } catch {
      readings = [];
    }
  });

  let events = $derived(buildTimelineEvents(readings, 30));
  let refillCount = $derived(events.filter((e) => e.kind === "refill").length);
  let totalReadings = $derived(events.length);

  const dotSize: Record<"tile" | "full", { normal: number; special: number }> = {
    tile: { normal: 4, special: 8 },
    full: { normal: 6, special: 12 },
  };
  const colours: Record<string, string> = {
    refill: "#10b981",
    anomaly: "#f59e0b",
    normal: "#3b82f6",
  };
</script>

<HeroShell
  {size}
  accent="slate"
  label="Records"
  range="30d"
  headline={`${totalReadings} readings · ${refillCount} refill${refillCount === 1 ? "" : "s"}`}
  sub="green = refill · amber = anomaly · blue = normal"
  href="/records"
>
  <div class={`relative w-full ${size === "tile" ? "h-[34px]" : "h-[100px]"}`}>
    <div class="absolute left-0 right-0 top-1/2 h-px bg-border-strong"></div>
    {#each events as e}
      {@const sz = e.kind === "normal" ? dotSize[size].normal : dotSize[size].special}
      <div
        class="absolute rounded-full"
        style={`left: calc(${e.position * 100}% - ${sz / 2}px); top: calc(50% - ${sz / 2}px); width: ${sz}px; height: ${sz}px; background:${colours[e.kind]};`}
      ></div>
    {/each}
  </div>
</HeroShell>
