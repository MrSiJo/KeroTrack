<script lang="ts">
  import { stringToArray, getSchedule } from "cron-converter";
  import cronstrue from "cronstrue";
  import { api, ApiError } from "$lib/api";
  import { settings } from "$lib/stores/settings";
  import { activeGroup, search } from "$lib/stores/settingsUi";
  import type { SettingDef, SettingItem } from "$lib/types/api";
  import RunPanel from "$lib/components/RunPanel.svelte";

  type Props = {
    pending: Record<string, unknown>;
    onChange: (key: string, value: unknown) => void;
  };
  let { pending, onChange }: Props = $props();

  let oldPassword = $state("");
  let newPassword = $state("");
  let confirmPassword = $state("");
  let pwSubmitting = $state(false);
  let pwError = $state<string | null>(null);
  let pwOk = $state(false);

  function defFor(key: string): SettingDef | undefined {
    return $settings.schema.find((d) => d.key === key);
  }
  function display(item: SettingItem): unknown {
    if (item.is_secret) return "";
    return pending[item.key] !== undefined ? pending[item.key] : item.value;
  }
  function describeCron(expr: string): string {
    if (!expr || typeof expr !== "string") return "";
    try {
      return cronstrue.toString(expr.trim(), { use24HourTimeFormat: true });
    } catch {
      return "";
    }
  }

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

  const HIDDEN_KEYS = new Set<string>(["web.title"]);

  const GROUP_ORDER: Record<string, string[]> = {
    mqtt: [
      "mqtt.broker",
      "mqtt.port",
      "mqtt.username",
      "mqtt.password",
      "mqtt.topic_readings",
      "mqtt.topic_analytics",
      "mqtt.topic_costanalysis",
      "mqtt.broadcast_interval_minutes",
      "mqtt.timeout_minutes",
    ],
  };

  function applyOrder(items: SettingItem[], group: string): SettingItem[] {
    const order = GROUP_ORDER[group];
    if (!order) return items;
    const idx = (k: string) => {
      const i = order.indexOf(k);
      return i === -1 ? Number.MAX_SAFE_INTEGER : i;
    };
    return [...items].sort((a, b) => idx(a.key) - idx(b.key));
  }

  let visibleItems = $derived(() => {
    const q = $search.trim().toLowerCase();
    if (q) {
      return $settings.items
        .filter((i) => !HIDDEN_KEYS.has(i.key))
        .filter(
          (i) =>
            i.key.toLowerCase().includes(q) ||
            (i.label ?? "").toLowerCase().includes(q),
        );
    }
    if ($activeGroup === "account") return [];
    if ($activeGroup === "maintenance") return [];
    return applyOrder(
      ($settings.groups[$activeGroup] ?? []).filter((i) => !HIDDEN_KEYS.has(i.key)),
      $activeGroup,
    );
  });

  let resettingGroup = $state(false);

  async function resetGroup() {
    const items = $settings.groups[$activeGroup] ?? [];
    if (!items.length) return;
    if (
      !confirm(
        `Reset all ${items.length} ${$activeGroup} settings to their default values? This is immediate; pending unsaved changes will be discarded.`,
      )
    ) {
      return;
    }
    resettingGroup = true;
    try {
      for (const item of items) {
        await api.resetSetting(item.key);
      }
      await settings.refresh();
    } catch (err) {
      console.error("reset failed", err);
    } finally {
      resettingGroup = false;
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
    if (newPassword.length < 12) {
      pwError = "New password must be at least 12 characters";
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
      pwError = err instanceof ApiError ? err.message : (err as Error).message;
    } finally {
      pwSubmitting = false;
    }
  }
</script>

<section class="flex-1 rounded-lg border border-border bg-bg-panel">
  <header class="flex items-center justify-between border-b border-border px-4 py-2">
    <div>
      <div class="text-xs font-medium uppercase tracking-wide text-text-muted">
        {$search.trim() ? "Search results" : $activeGroup}
      </div>
      <div class="text-[11px] text-text-subtle">
        {$search.trim()
          ? `${visibleItems().length} match${visibleItems().length === 1 ? "" : "es"}`
          : `${visibleItems().length} setting${visibleItems().length === 1 ? "" : "s"}`}
      </div>
    </div>
    {#if !$search.trim() && $activeGroup !== "account" && $activeGroup !== "maintenance"}
      <button
        type="button"
        class="rounded border border-border px-2 py-1 text-[11px] text-text-muted hover:border-border-strong hover:text-text disabled:opacity-50"
        onclick={resetGroup}
        disabled={resettingGroup}
      >
        {resettingGroup ? "Resetting…" : `Reset ${$activeGroup}`}
      </button>
    {/if}
  </header>

  {#if $activeGroup === "account" && !$search.trim()}
    <form class="grid max-w-md gap-3 px-4 py-4" onsubmit={changePassword}>
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
        placeholder="New password (min 12 chars)"
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
  {:else if $activeGroup === "maintenance" && !$search.trim()}
    <div class="px-4 py-4">
      <RunPanel />
    </div>
  {:else}
    <div class="divide-y divide-border">
      {#each visibleItems() as item (item.key)}
        {@const def = defFor(item.key)}
        <div class="group grid grid-cols-12 items-center gap-3 px-4 py-2.5">
          <label class="col-span-5 text-sm text-text">
            <span class="inline-flex items-center gap-1">
              {def?.label ?? item.label}
              {#if def?.description}
                <span class="info group relative inline-block cursor-help text-text-subtle" tabindex="0" aria-label={def.description}>
                  ⓘ
                  <span class="pointer-events-none invisible absolute left-1/2 top-full z-10 mt-1 w-64 -translate-x-1/2 rounded border border-border bg-bg-elev px-2 py-1 text-[11px] text-text shadow-lg group-hover:visible group-focus:visible">
                    {def.description}
                  </span>
                </span>
              {/if}
            </span>
            <div class="font-mono text-[10px] text-text-subtle opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">{item.key}</div>
          </label>
          <div class="col-span-7">
            {#if item.key === "notifications.apprise_urls"}
              {@const lines = Array.isArray(display(item)) ? (display(item) as string[]).join("\n") : ""}
              <textarea
                class="w-full rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                rows="3"
                placeholder="One URL per line — e.g. gotify://192.168.1.10/AbC123"
                oninput={(e) => {
                  const raw = (e.currentTarget as HTMLTextAreaElement).value;
                  const arr = raw.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
                  onChange(item.key, arr);
                }}
                >{lines}</textarea
              >
            {:else if item.key === "web.theme_default"}
              <select
                class="w-32 rounded border border-border bg-bg-elev px-2 py-1 text-xs"
                value={display(item) as string}
                onchange={(e) => onChange(item.key, (e.currentTarget as HTMLSelectElement).value)}
              >
                <option value="dark">Dark</option>
                <option value="light">Light</option>
                <option value="system">System (auto)</option>
              </select>
            {:else if item.value_type === "bool"}
              <input
                type="checkbox"
                checked={display(item) as boolean}
                onchange={(e) => onChange(item.key, (e.currentTarget as HTMLInputElement).checked)}
              />
            {:else if item.value_type === "json"}
              <textarea
                class="w-full rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                rows="2"
                oninput={(e) => {
                  try {
                    onChange(item.key, JSON.parse((e.currentTarget as HTMLTextAreaElement).value));
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
                oninput={(e) => onChange(item.key, (e.currentTarget as HTMLInputElement).value)}
              />
            {:else if item.value_type === "cron"}
              {@const cronValue = (display(item) ?? "") as string}
              {@const fires = nextCronFires(cronValue)}
              <input
                type="text"
                class="w-full rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                value={cronValue}
                oninput={(e) => onChange(item.key, (e.currentTarget as HTMLInputElement).value)}
              />
              {#if cronValue.trim()}
                {@const human = describeCron(cronValue)}
                {#if human}
                  <div class="mt-1 text-[11px] text-text-muted">{human}</div>
                {/if}
              {/if}
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
                class="w-32 rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                value={display(item) as number}
                oninput={(e) => {
                  const raw = (e.currentTarget as HTMLInputElement).value;
                  onChange(item.key, item.value_type === "int" ? parseInt(raw, 10) : parseFloat(raw));
                }}
              />
            {:else}
              <input
                type="text"
                class="w-full rounded border border-border bg-bg-elev px-2 py-1 font-mono text-xs"
                value={display(item) as string}
                oninput={(e) => onChange(item.key, (e.currentTarget as HTMLInputElement).value)}
              />
            {/if}
          </div>
        </div>
      {/each}
      {#if visibleItems().length === 0}
        <p class="px-4 py-6 text-sm text-text-subtle">No matches.</p>
      {/if}
    </div>
  {/if}
</section>
