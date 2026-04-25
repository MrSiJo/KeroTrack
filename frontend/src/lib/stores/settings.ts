import { writable } from "svelte/store";

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

  async function save(diff: Record<string, unknown>): Promise<void> {
    await api.bulkSetSettings(diff);
    await refresh();
  }

  return { subscribe, refresh, save };
}

export const settings = createSettings();
