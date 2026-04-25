import { writable, type Readable } from "svelte/store";

import { api, onUnauthorised, setCsrfToken } from "$lib/api";

export type AuthState = {
  loading: boolean;
  needsSetup: boolean | null;
  user: string | null;
  csrfToken: string | null;
  error: string | null;
};

const initialState: AuthState = {
  loading: true,
  needsSetup: null,
  user: null,
  csrfToken: null,
  error: null,
};

function createAuth() {
  const { subscribe, update } = writable<AuthState>(initialState);

  function setUser(user: string | null, csrfToken: string | null): void {
    setCsrfToken(csrfToken);
    update((s) => ({ ...s, user, csrfToken, error: null }));
  }

  async function refresh(): Promise<void> {
    update((s) => ({ ...s, loading: true, error: null }));
    try {
      const status = await api.setupStatus();
      if (status.needs_setup) {
        update((s) => ({
          ...s,
          loading: false,
          needsSetup: true,
          user: null,
          csrfToken: null,
        }));
        return;
      }
      try {
        const me = await api.me();
        setUser(me.username, me.csrf_token);
        update((s) => ({ ...s, loading: false, needsSetup: false }));
      } catch {
        update((s) => ({
          ...s,
          loading: false,
          needsSetup: false,
          user: null,
          csrfToken: null,
        }));
      }
    } catch (err) {
      update((s) => ({
        ...s,
        loading: false,
        error: (err as Error).message,
      }));
    }
  }

  async function login(username: string, password: string): Promise<void> {
    const resp = await api.login(username, password);
    setUser(resp.username, resp.csrf_token);
    update((s) => ({ ...s, needsSetup: false, loading: false }));
  }

  async function setup(username: string, password: string): Promise<void> {
    await api.setup(username, password);
    await login(username, password);
  }

  async function logout(): Promise<void> {
    try {
      await api.logout();
    } catch {
      /* ignore */
    }
    setUser(null, null);
  }

  onUnauthorised(() => setUser(null, null));

  return {
    subscribe,
    refresh,
    login,
    setup,
    logout,
  } satisfies Readable<AuthState> & Record<string, unknown>;
}

export const auth = createAuth();
