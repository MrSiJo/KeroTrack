<script lang="ts">
  import { onMount } from "svelte";
  import { stringToArray, getSchedule } from "cron-converter";

  import { api, ApiError } from "$lib/api";
  import { settings } from "$lib/stores/settings";
  import type { SettingDef, SettingItem } from "$lib/types/api";

  function nextCronFires(expr: string, count = 3): string[] {
    if (!expr || typeof expr !== "string") return [];
    try {
      const arr = stringToArray(expr.trim());
      const sched = getSchedule(arr, new Date());
      const fmt = new Intl.DateTimeFormat(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
      return Array.from({ length: count }, () => fmt.format(sched.next().toDate()));
    } catch {
      return [];
    }
  }

  let pending = $state<Record<string, unknown>>({});
  let saving = $state(false);
  let saveError = $state<string | null>(null);
  let saveOk = $state(false);

  // Change-password form
  let oldPassword = $state("");
  let newPassword = $state("");
  let confirmPassword = $state("");
  let pwSubmitting = $state(false);
  let pwError = $state<string | null>(null);
  let pwOk = $state(false);

  onMount(() => {
    void settings.refresh();
  });

  function defFor(key: string): SettingDef | undefined {
    return $settings.schema.find((d) => d.key === key);
  }

  function display(item: SettingItem): unknown {
    if (item.is_secret) return "";
    return pending[item.key] !== undefined ? pending[item.key] : item.value;
  }

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
      saveError =
        err instanceof ApiError ? err.message : (err as Error).message;
    } finally {
      saving = false;
    }
  }

  async function changePassword(e: Event) {
    e.preventDefault();
    pwError = null;
    pwOk = false;
    if (newPassword !== confirmPassword) {
      pwError = "Passwords don't match";
      return;
    }
    if (newPassword.length < 8) {
      pwError = "New password must be at least 8 characters";
      return;
    }
    pwSubmitting = true;
    try {
      await api.changePassword(oldPassword, newPassword);
      pwOk = true;
      oldPassword = "";
      newPassword = "";
      confirmPassword = "";
    } catch (err) {
      pwError =
        err instanceof ApiError ? err.message : (err as Error).message;
    } finally {
      pwSubmitting = false;
    }
  }

  // group label sort
  $effect(() => {
    if (!$settings.items.length) return;
  });
</script>

<div class="space-y-6">
  <header class="flex items-center justify-between">
    <h1 class="text-lg font-semibold">Settings</h1>
    <div class="flex items-center gap-3">
      {#if saveError}<span class="text-xs text-brand-red">{saveError}</span>{/if}
      {#if saveOk}<span class="text-xs text-brand-emerald">Saved</span>{/if}
      <button
        class="rounded bg-brand-blue px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        on:click={save}
        disabled={saving || !Object.keys(pending).length}
      >
        {saving ? "Saving…" : `Save${Object.keys(pending).length ? ` (${Object.keys(pending).length})` : ""}`}
      </button>
    </div>
  </header>

  {#if $settings.error}
    <p class="text-xs text-brand-red">{$settings.error}</p>
  {/if}

  {#each Object.entries($settings.groups) as [group, items] (group)}
    <details
      class="rounded-lg border border-border bg-bg-panel"
      open={group === "tank" || group === "mqtt" || group === "schedule"}
    >
      <summary
        class="cursor-pointer border-b border-border px-4 py-2 text-sm font-medium uppercase tracking-wide text-text-muted"
      >
        {group}
      </summary>
      <div class="divide-y divide-border">
        {#each items as item (item.key)}
          {@const def = defFor(item.key)}
          <div class="grid grid-cols-12 items-center gap-3 px-4 py-2.5">
            <label class="col-span-5 text-sm text-text">
              {def?.label ?? item.label}
              <div class="text-xs text-text-subtle">{item.key}</div>
            </label>
            <div class="col-span-7">
              {#if item.value_type === "bool"}
                <input
                  type="checkbox"
                  checked={display(item) as boolean}
                  on:change={(e) =>
                    setPending(item.key, (e.currentTarget as HTMLInputElement).checked)}
                />
              {:else if item.value_type === "json"}
                <textarea
                  class="w-full rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                  rows="2"
                  on:input={(e) => {
                    try {
                      setPending(
                        item.key,
                        JSON.parse((e.currentTarget as HTMLTextAreaElement).value),
                      );
                    } catch {
                      /* keep typing */
                    }
                  }}
                  >{JSON.stringify(display(item) ?? [], null, 2)}</textarea
                >
              {:else if item.value_type === "secret"}
                <input
                  type="password"
                  placeholder="(unchanged — type to set new value)"
                  class="w-full rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                  on:input={(e) =>
                    setPending(item.key, (e.currentTarget as HTMLInputElement).value)}
                />
              {:else if item.value_type === "cron"}
                {@const cronValue = (display(item) ?? "") as string}
                {@const fires = nextCronFires(cronValue)}
                <input
                  type="text"
                  class="w-full rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                  value={cronValue}
                  on:input={(e) =>
                    setPending(item.key, (e.currentTarget as HTMLInputElement).value)}
                />
                {#if fires.length > 0}
                  <div class="mt-1 space-y-0.5 text-xs text-text-subtle">
                    <div class="font-medium text-text-muted">Next 3 fires:</div>
                    {#each fires as fire}
                      <div>· {fire}</div>
                    {/each}
                  </div>
                {:else if cronValue.trim()}
                  <div class="mt-1 text-xs text-brand-red">Invalid cron expression</div>
                {/if}
              {:else if item.value_type === "int" || item.value_type === "float"}
                <input
                  type="number"
                  step={def?.step ?? (item.value_type === "int" ? 1 : "any")}
                  class="w-40 rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                  value={display(item) as number}
                  on:input={(e) => {
                    const raw = (e.currentTarget as HTMLInputElement).value;
                    setPending(
                      item.key,
                      item.value_type === "int" ? parseInt(raw, 10) : parseFloat(raw),
                    );
                  }}
                />
              {:else}
                <input
                  type="text"
                  class="w-full rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                  value={display(item) as string}
                  on:input={(e) =>
                    setPending(item.key, (e.currentTarget as HTMLInputElement).value)}
                />
              {/if}
              {#if def?.description}
                <div class="mt-1 text-xs text-text-subtle">{def.description}</div>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    </details>
  {/each}

  <section class="rounded-lg border border-border bg-bg-panel p-5">
    <h2 class="text-sm font-semibold">Change password</h2>
    <p class="mt-1 text-xs text-text-subtle">
      Rotates the operator credential. The old one stops working immediately.
    </p>
    <form class="mt-4 grid max-w-md gap-3" on:submit={changePassword}>
      <input
        type="password"
        placeholder="Current password"
        class="rounded border border-border bg-bg-elev px-2 py-1.5 text-sm"
        bind:value={oldPassword}
        autocomplete="current-password"
        required
      />
      <input
        type="password"
        placeholder="New password"
        class="rounded border border-border bg-bg-elev px-2 py-1.5 text-sm"
        bind:value={newPassword}
        autocomplete="new-password"
        required
      />
      <input
        type="password"
        placeholder="Confirm new password"
        class="rounded border border-border bg-bg-elev px-2 py-1.5 text-sm"
        bind:value={confirmPassword}
        autocomplete="new-password"
        required
      />
      {#if pwError}<p class="text-xs text-brand-red">{pwError}</p>{/if}
      {#if pwOk}<p class="text-xs text-brand-emerald">Password updated.</p>{/if}
      <button
        type="submit"
        class="w-fit rounded bg-brand-blue px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        disabled={pwSubmitting}
      >
        {pwSubmitting ? "Updating…" : "Update password"}
      </button>
    </form>
  </section>
</div>
