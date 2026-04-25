// Hand-mirrored API contract — keep in sync with backend Phase 5 routes.

export type SettingType =
  | "string"
  | "int"
  | "float"
  | "bool"
  | "cron"
  | "json"
  | "secret";

export type SettingDef = {
  key: string;
  value_type: SettingType;
  group: string;
  label: string;
  description: string | null;
  default: unknown;
  is_secret: boolean;
  requires_restart: boolean;
  min_value: number | null;
  max_value: number | null;
  step: number | null;
};

export type SettingItem = {
  key: string;
  value: unknown;
  value_type: SettingType;
  group: string;
  label: string;
  description: string | null;
  is_secret: boolean;
  default?: unknown;
};

export type HealthPayload = {
  status: "ok" | "degraded";
  db: "ok" | "down" | "unknown";
  mqtt_connected: boolean;
  last_reading_at: string | null;
  age_seconds: number | null;
  scheduler_running: boolean;
};

export type Reading = {
  date: string;
  id: string;
  temperature: number | null;
  litres_remaining: number | null;
  litres_used_since_last: number | null;
  percentage_remaining: number | null;
  oil_depth_cm: number | null;
  air_gap_cm: number | null;
  current_ppl: number | null;
  cost_used: string | null;
  cost_to_fill: string | null;
  heating_degree_days: number | null;
  seasonal_efficiency: number | null;
  refill_detected: string | null;
  leak_detected: string | null;
  raw_flags: string | null;
  litres_to_order: number | null;
  bars_remaining: number | null;
};

export type AnalysisResult = {
  latest_reading_date: string;
  latest_analysis_date: string | null;
  latest_reading_refill_detected: string | null;
  latest_reading_leak_detected: string | null;
  days_since_refill: number | null;
  total_consumption_since_refill: number | null;
  avg_daily_consumption_l: number | null;
  estimated_days_remaining: number | null;
  estimated_empty_date: string | null;
  consumption_per_hdd_l: number | null;
  upcoming_month_hdd: number | null;
  estimated_daily_consumption_hdd_l: number | null;
  estimated_daily_hot_water_consumption_l: number | null;
  estimated_daily_heating_consumption_l: number | null;
  seasonal_heating_factor: number | null;
  remaining_days_empty_hdd: number | null;
  remaining_date_empty_hdd: string | null;
};

export type StatusPayload = {
  reading: Reading | null;
  analysis: AnalysisResult | null;
  cost: Record<string, unknown> | null;
};

export type LoginResponse = {
  username: string;
  csrf_token: string;
};

export type SetupStatus = { needs_setup: boolean };
