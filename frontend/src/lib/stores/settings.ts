import { get, writable } from "svelte/store";

import { api } from "$lib/api";
import type { SettingDef, SettingItem } from "$lib/types/api";

export type SettingsState = {
  schema: SettingDef[];
  items: SettingItem[];
  groups: Record<string, SettingItem[]>;
  loading: boolean;
  error: string | null;
};

const initial: SettingsState = {
  schema: [],
  items: [],
  groups: {},
  loading: false,
  error: null,
};

export type SaveError = { key: string; label: string; message: string };
export type SaveResult = {
  ok: boolean;
  saved: string[];
  errors: SaveError[];
};

export function formatSaveErrors(errors: SaveError[]): string {
  return `Not saved: ${errors.map((e) => `${e.label} (${e.message})`).join("; ")}`;
}

function createSettings() {
  const { subscribe, update } = writable<SettingsState>(initial);

  async function refresh(): Promise<void> {
    update((s) => ({ ...s, loading: true, error: null }));
    try {
      const [schema, snapshot] = await Promise.all([
        api.settingsSchema(),
        api.settings(),
      ]);
      update(() => ({
        schema: schema.catalogue,
        items: snapshot.items,
        groups: snapshot.groups,
        loading: false,
        error: null,
      }));
    } catch (err) {
      update((s) => ({ ...s, loading: false, error: (err as Error).message }));
    }
  }

  // The bulk endpoint answers 200 even when some keys are rejected, so a
  // non-empty `errors` list is a failure the caller must surface.
  async function save(diff: Record<string, unknown>): Promise<SaveResult> {
    const res = await api.bulkSetSettings(diff);
    await refresh();
    const state = get({ subscribe });
    const labelFor = (key: string) =>
      state.schema.find((d) => d.key === key)?.label ??
      state.items.find((i) => i.key === key)?.label ??
      key;
    const errors = (res.errors ?? []).map((e) => ({
      key: e.key,
      label: labelFor(e.key),
      message: e.message,
    }));
    return { ok: errors.length === 0, saved: res.saved ?? [], errors };
  }

  return { subscribe, refresh, save };
}

export const settings = createSettings();
