<script lang="ts">
  import { settings } from "$lib/stores/settings";
  import { activeGroup, search } from "$lib/stores/settingsUi";

  let groupEntries = $derived(() => {
    const entries = Object.entries($settings.groups).map(
      ([g, items]) => ({ group: g, count: items.length }),
    );
    entries.push({ group: "maintenance", count: 1 });
    entries.push({ group: "account", count: 1 });
    return entries;
  });

  function setActive(g: string) {
    activeGroup.set(g);
  }
</script>

<aside class="flex w-44 flex-col gap-2 rounded-lg border border-border bg-bg-panel p-2">
  <input
    type="text"
    class="w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-xs text-text placeholder:text-text-subtle"
    placeholder="Search settings…"
    bind:value={$search}
  />
  <nav class="flex flex-col gap-px">
    {#each groupEntries() as { group, count } (group)}
      <button
        type="button"
        class={`flex items-center justify-between rounded px-2 py-1 text-left text-xs ${$activeGroup === group ? "border-l-2 border-brand-blue bg-bg-elev pl-1.5 text-text" : "text-text-muted hover:text-text"}`}
        onclick={() => setActive(group)}
      >
        <span class="capitalize">{group}</span>
        <span class="rounded bg-border px-1.5 py-0.5 font-mono text-[10px] text-text-subtle">{count}</span>
      </button>
    {/each}
  </nav>
</aside>
