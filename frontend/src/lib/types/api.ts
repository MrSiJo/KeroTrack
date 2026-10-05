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

/** `oiltank/cost_analysis` payload. Only the keys the UI relies on are
 * typed; the rest stay open. */
export type CostAnalysisResult = {
  /** Days since the last logged refill date (else the latest period
   * boundary); same meaning as AnalysisResult.days_since_refill. */
  days_since_refill: number | null;
  /** Days since the latest refill period ended (the old meaning of
   * days_since_refill on this payload). */
  days_since_period_end: number | null;
  [key: string]: unknown;
};

export type StatusPayload = {
  reading: Reading | null;
  analysis: AnalysisResult | null;
  cost: CostAnalysisResult | null;
};

export type LoginResponse = {
  username: string;
  csrf_token: string;
};

export type SetupStatus = { needs_setup: boolean };

// ----- buying planner ------------------------------------------------

export type BuyingState =
  | "buy_now"
  | "deadline"
  | "overdue"
  | "no_room"
  | "wait"
  | "unknown";

export type BuyingQuote = {
  id: number;
  fetched_at: string;
  supplier: string;
  kind: string;
  litres: number | null;
  delivery_by: string | null;
  delivery_label: string | null;
  urgent: number;
  ppl_net: number | null;
  total_inc_vat: number | null;
  fees_inc_vat: number | null;
  ppl_effective: number | null;
  ok: number;
  error: string | null;
};

export type BuyingScenario = {
  run_out: string | null;
  order_by: string | null;
  next_order_by: string | null;
  /** Weekly points: [isoDate, litres]. */
  series: [string, number][];
};

export type HeatingModel = "nest" | "hdd";

export type BuyingSummary = {
  state: BuyingState;
  updated_at: string | null;
  trigger_ppl: number | null;
  headroom_l: number | null;
  best: {
    supplier: string;
    total_inc_vat: number;
    /** All in pence per litre (VAT, delivery, fees): the trigger's basis. */
    ppl?: number | null;
    ppl_effective: number;
    delivery_label: string | null;
    fetched_at: string;
  } | null;
  quotes: BuyingQuote[];
  scenarios: Record<string, BuyingScenario>;
  active_scenario: string | null;
  k: number | null;
  hw_l_per_day: number | null;
  /** Which heating model the runway uses. */
  heating_model?: HeatingModel;
  /** Litres per Nest heating hour; set under the Nest model only. */
  l_per_heating_hour?: number | null;
  context: {
    index_percentile_365d: number | null;
    /** Pence, positive means dearer. */
    best_change_30d: number | null;
    spread_today: number | null;
  };
};

export type BuyingCalibration = {
  k: number | null;
  hw_fixed_l: number | null;
  free_hw_l: number | null;
  free_k: number | null;
  proposed_burner_minutes: number | null;
  hw_floor_l: number | null;
  mae_l: number | null;
  days_used: number;
  heating_days: number;
  current_burner_minutes: number | null;
  current_hw_l_per_day: number | null;
  heating_model?: HeatingModel;
  /** Fixed hot water fit: the one the runway uses under the Nest model. */
  l_per_heating_hour?: number | null;
  l_per_heating_hour_free?: number | null;
  hw_per_day_nest?: number | null;
  nest_months_used?: number | null;
  nest_months_excluded?: number | null;
};
