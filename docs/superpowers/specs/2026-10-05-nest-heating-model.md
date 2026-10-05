# Nest heating hours as the heating signal

**Status:** Approved by the owner 2026-10-05 (option A: Home Assistant publishes daily heating hours).
**Date:** 2026-10-05

## Why

The boiler fires the same way for hot water and heating; the Nest decides demand. Tank-temperature degree days are a weak proxy for heating demand: they are above zero almost every day, so the hot water / heating split is unidentified. The owner's Nest monthly Home Report emails give 48 months of real heating hours (2022-04 to 2026-08). Fitting the 13 clean months of measured usage:

| Model | Hot water | Heating | Monthly error |
|---|---|---|---|
| Tank HDD (current) | 0.29 L/day | 0.19 L/HDD | 7.4 L |
| **Nest hours** | **0.87 L/day** | **0.74 L per heating hour** | **6.3 L** |

Summer months have zero heating hours, so hot water is anchored by data (0.87 L/day = about 16 burner minutes per slot at 2.33 L/h). 0.74 L per heating hour means the burner fires about 32% of the time the Nest calls for heat.

## Data sources

1. **Back-fill:** monthly heating hours imported once on production via a new CLI command `import-nest-months <csv>` (columns `month,heating_hours,source`). The owner's figures never go in the repo; tests use synthetic values.
2. **Ongoing:** Home Assistant publishes one message per day to MQTT topic `mqtt.topic_nest_heating` (new setting, default `kerotrack/nest_heating`), payload `{"date": "YYYY-MM-DD", "heating_hours": 1.25}`, retained, sent at 23:58 local. KeroTrack stores it as a daily row (upsert by date).
3. Hot water boosts started manually on the Nest are not observable; they are small next to the schedule and accepted as noise.

## Storage

- `nest_heating_daily(date TEXT PK, heating_hours REAL, received_at TEXT)`.
- `nest_heating_monthly(month TEXT PK 'YYYY-MM', heating_hours REAL, source TEXT 'report'|'prev'|'daily')`.
- Monthly totals for months covered by daily rows (>= 25 days present) are computed from the daily rows and upserted with source `daily`; imported `report` rows are never overwritten by a partial daily month.

## Model

- **Calibration (monthly):** for months with Nest hours and at least 20 bucketed usage days: `used_month = hw_per_day * days + a * nest_hours`, ordinary least squares on per-month totals. Needs >= 6 such months including at least 2 with zero heating hours; otherwise fall back to the existing HDD calibration. Output adds `heating_model: "nest" | "hdd"`, `l_per_heating_hour`, `nest_months_used`, and the proposed burner minutes from `hw_per_day` (only when > 0).
- **Projection:** when the Nest model is active (>= 12 months of Nest data and a calibrated `a`), the heating term for day d is `a * expected_hours(d) * multiplier(scenario, month(d))`, where `expected_hours(d)` = mean heating hours for d's calendar month across all years with data, divided by that month's days. Hot water stays from the schedule setting (unchanged). Otherwise the HDD model runs as today.
- The analysis job's `estimated_daily_heating_consumption_l` uses `a * expected_hours(today)` under the Nest model, with `heating_estimate_basis = "nest"`.
- The summary gains `heating_model`, `l_per_heating_hour` (or null), and keeps `k` for the HDD model.

## UI

- Forecast stats: the fourth card shows "Heating: 0.74 L per heating hour (Nest)" under the Nest model, else "Heating factor k".
- Calibration panel shows which model was used and the proposal.

## Home Assistant (owner approved)

- Template binary sensor `binary_sensor.nest_heating_active`: on when `state_attr('climate.living_room', 'hvac_action') == 'heating'`.
- `history_stats` sensor `sensor.nest_heating_hours_today`: time on, today from midnight.
- Automation "KeroTrack - publish Nest heating hours": at 23:58 publish retained `{"date": now().date(), "heating_hours": sensor value}` to `kerotrack/nest_heating`.

## Out of scope

Parsing emails automatically; a Settings form for monthly entry; changing the owner's burner minutes (proposal only).

## Verification

Unit tests for storage, CLI import, MQTT ingest of the daily payload, monthly roll-up rules, Nest calibration (recovers known hw and a from synthetic months; falls back to HDD with too few months), projection under both models; rehearsal on a copy of production data with the 48 months imported.
