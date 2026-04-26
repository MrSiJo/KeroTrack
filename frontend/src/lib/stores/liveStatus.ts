import { writable } from "svelte/store";

import { api } from "$lib/api";
import type { HealthPayload, StatusPayload } from "$lib/types/api";

export type LiveStatusState = {
  health: HealthPayload | null;
  status: StatusPayload | null;
  loading: boolean;
  error: string | null;
};

const initial: LiveStatusState = {
  health: null,
  status: null,
  loading: false,
  error: null,
};

function createLiveStatus() {
  const { subscribe, update, set } = writable<LiveStatusState>(initial);
  let source: EventSource | null = null;

  async function refresh(): Promise<void> {
    update((s) => ({ ...s, loading: true }));
    try {
      const [health, status] = await Promise.all([
        api.health(),
        api.status().catch(() => null),
      ]);
      update((s) => ({
        ...s,
        health,
        status: status ?? s.status,
        loading: false,
        error: null,
      }));
    } catch (err) {
      update((s) => ({
        ...s,
        loading: false,
        error: (err as Error).message,
      }));
    }
  }

  function start(): void {
    if (typeof window === "undefined") return;
    if (source) return;
    source = new EventSource("/api/stream", { withCredentials: true });
    const onAny = () => {
      void refresh();
    };
    source.addEventListener("reading", onAny);
    source.addEventListener("analysis", onAny);
    source.addEventListener("cost_analysis", onAny);
    source.addEventListener("mqtt_message", onAny);
    source.onerror = () => {
      // browser will auto-reconnect; nothing to do
    };
  }

  function stop(): void {
    source?.close();
    source = null;
  }

  return { subscribe, refresh, start, stop };
}

export const liveStatus = createLiveStatus();
