// Typed fetch client. Sends `credentials: 'include'`, attaches the CSRF
// token (when known) for mutating verbs, and routes 401 responses through
// a registered callback so the auth store can clear state and redirect.

import type {
  AnalysisResult,
  HealthPayload,
  LoginResponse,
  Reading,
  SettingDef,
  SettingItem,
  SetupStatus,
  StatusPayload,
} from "$lib/types/api";

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

let csrfToken: string | null = null;
let onUnauthorisedCb: (() => void) | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

export function onUnauthorised(cb: () => void): void {
  onUnauthorisedCb = cb;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public field?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (MUTATING.has(method) && csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  const resp = await fetch(path, {
    method,
    headers,
    credentials: "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (resp.status === 401) {
    onUnauthorisedCb?.();
    throw new ApiError(401, "auth_required", "Authentication required");
  }
  const text = await resp.text();
  const data = text ? safeJson(text) : null;
  if (!resp.ok) {
    const detail = data && typeof data === "object" ? data : {};
    const code =
      (detail as { error?: string; detail?: { error?: string } }).error ??
      (detail as { detail?: { error?: string } }).detail?.error ??
      `http_${resp.status}`;
    const msg =
      (detail as { message?: string; detail?: { message?: string } }).message ??
      (detail as { detail?: { message?: string } }).detail?.message ??
      resp.statusText;
    const field = (detail as { field?: string }).field;
    throw new ApiError(resp.status, code, msg, field);
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export const api = {
  // ----- auth + setup ------------------------------------------------
  setupStatus: () => request<SetupStatus>("GET", "/api/setup/status"),
  setup: (username: string, password: string) =>
    request<{ username: string }>("POST", "/api/setup", { username, password }),
  login: (username: string, password: string) =>
    request<LoginResponse>("POST", "/api/auth/login", { username, password }),
  me: () => request<LoginResponse>("GET", "/api/auth/me"),
  logout: () => request<{ ok: boolean }>("POST", "/api/auth/logout"),
  changePassword: (oldPassword: string, newPassword: string) =>
    request<{ ok: boolean }>("POST", "/api/auth/change-password", {
      old_password: oldPassword,
      new_password: newPassword,
    }),

  // ----- read endpoints ---------------------------------------------
  health: () => request<HealthPayload>("GET", "/api/health"),
  status: () => request<StatusPayload>("GET", "/api/status"),
  readings: (params?: {
    limit?: number;
    offset?: number;
    order?: "asc" | "desc";
    since?: string;
    until?: string;
  }) => {
    const q = new URLSearchParams();
    if (params?.limit !== undefined) q.set("limit", String(params.limit));
    if (params?.offset !== undefined) q.set("offset", String(params.offset));
    if (params?.order) q.set("order", params.order);
    if (params?.since) q.set("since", params.since);
    if (params?.until) q.set("until", params.until);
    const qs = q.toString();
    return request<{
      total: number;
      items: Reading[];
      limit: number;
      offset: number;
    }>("GET", `/api/readings${qs ? `?${qs}` : ""}`);
  },
  reading: (date: string) =>
    request<Reading>("GET", `/api/readings/${encodeURIComponent(date)}`),
  patchReading: (date: string, patch: Partial<Reading>) =>
    request<Reading>(
      "PATCH",
      `/api/readings/${encodeURIComponent(date)}`,
      patch,
    ),
  deleteReading: (date: string) =>
    request<{ ok: boolean }>(
      "DELETE",
      `/api/readings/${encodeURIComponent(date)}`,
    ),

  analysisLatest: () =>
    request<AnalysisResult>("GET", "/api/analysis/latest"),
  analysisHistory: (limit = 200) =>
    request<{ items: AnalysisResult[] }>(
      "GET",
      `/api/analysis/history?limit=${limit}`,
    ),

  costsSummary: () => request<Record<string, unknown>>("GET", "/api/costs/summary"),
  costPeriods: () =>
    request<{ items: Record<string, unknown>[] }>("GET", "/api/costs/periods"),

  refills: () =>
    request<{ items: Record<string, unknown>[] }>("GET", "/api/refills"),
  createRefill: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>("POST", "/api/refills", body),
  deleteRefill: (date: string) =>
    request<{ ok: boolean }>(
      "DELETE",
      `/api/refills/${encodeURIComponent(date)}`,
    ),

  hdd: () => request<{ items: { date: string; hdd: number }[] }>("GET", "/api/hdd"),
  mqttFeed: (limit = 50) =>
    request<{ items: { topic: string; payload: unknown; ts: number }[] }>(
      "GET",
      `/api/mqtt-feed?limit=${limit}`,
    ),

  // ----- settings ---------------------------------------------------
  settings: () =>
    request<{
      groups: Record<string, SettingItem[]>;
      items: SettingItem[];
    }>("GET", "/api/settings"),
  settingsSchema: () =>
    request<{ catalogue: SettingDef[] }>("GET", "/api/settings/schema"),
  setSetting: (key: string, value: unknown) =>
    request<{ key: string; value: unknown }>(
      "PUT",
      `/api/settings/${encodeURIComponent(key)}`,
      { value },
    ),
  bulkSetSettings: (diff: Record<string, unknown>) =>
    request<{ saved: string[]; errors?: { key: string; message: string }[] }>(
      "PUT",
      "/api/settings",
      diff,
    ),
  resetSetting: (key: string) =>
    request<{ key: string; value: unknown }>(
      "POST",
      `/api/settings/${encodeURIComponent(key)}/reset`,
    ),

  // ----- admin ------------------------------------------------------
  runJob: (name: string, opts: { test?: boolean } = {}) =>
    request<Record<string, unknown>>("POST", `/api/admin/jobs/${name}/run`, opts),
  reloadSettings: () =>
    request<{ ok: boolean }>("POST", "/api/admin/reload-settings", {}),
};
