<script lang="ts">
  import { onMount } from "svelte";
  import SettingsForm from "$lib/components/SettingsForm.svelte";
  import SettingsNav from "$lib/components/SettingsNav.svelte";
  import { ApiError } from "$lib/api";
  import { settings } from "$lib/stores/settings";

  let pending = $state<Record<string, unknown>>({});
  let saving = $state(false);
  let saveError = $state<string | null>(null);
  let saveOk = $state(false);

  onMount(() => {
    void settings.refresh();
  });

  function setPending(key: string, value: unknown) {
    pending = { ...pending, [key]: value };
    saveOk = false;
  }

  async function save() {
    if (!Object.keys(pending).length) return;
    saving = true;
    saveError = null;
    try {
      await settings.save(pending);
      pending = {};
      saveOk = true;
    } catch (err) {
      saveError = err instanceof ApiError ? err.message : (err as Error).message;
    } finally {
      saving = false;
    }
  }
</script>

<div class="space-y-4">
  <header class="flex items-center justify-between">
    <h1 class="text-lg font-semibold">Settings</h1>
    <div class="flex items-center gap-3">
      {#if saveError}<span class="text-xs text-brand-red">{saveError}</span>{/if}
      {#if saveOk}<span class="text-xs text-brand-emerald">Saved</span>{/if}
      <button
        class="rounded bg-brand-blue px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        onclick={save}
        disabled={saving || !Object.keys(pending).length}
      >
        {saving ? "Saving…" : `Save${Object.keys(pending).length ? ` (${Object.keys(pending).length})` : ""}`}
      </button>
    </div>
  </header>

  {#if $settings.error}
    <p class="text-xs text-brand-red">{$settings.error}</p>
  {/if}

  <div class="flex items-start gap-4">
    <SettingsNav />
    <SettingsForm {pending} onChange={setPending} />
  </div>
</div>
