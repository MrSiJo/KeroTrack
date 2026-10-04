# Buy planner and analysis fixes

**Status:** Approved by the owner 2026-10-04. Supersedes and replaces `2026-08-13-scheduler-weekday-and-heating-estimate-design.md` (deleted; its still relevant content is merged here).
**Date:** 2026-10-04

## Why

The owner buys heating oil in 500 L minimum orders, shops around every time, never places emergency orders, and wants to buy on a dip rather than at a winter peak. KeroTrack can't currently support that, and several existing outputs are wrong:

1. **No real prices.** KeroTrack tracks only national averages. One of its two sources (yournrg) does not deliver to the owner's area, and national figures leave out supplier fees. BoilerJuice has the second lowest price per litre but its £12.98 service charge puts it fourth on total.
2. **The empty date ignores winter.** `estimated_days_remaining` divides the level by a flat daily rate. In autumn that rate is hot water only, so on 2026-09-28 it said "empty 2027-05-12". Last winter's real usage says usable oil runs out around the end of February.
3. **Hot water is a hard coded guess.** 10 sessions × 0.5 h burner × fuel rate × 1.1 = 1.83 L/day, about 2.5 to 6 times what the data fits.
4. **The heating estimate is stuck at its 15.0 clamp** (7 of the last 8 weekly runs).
5. **The weekly and monthly summaries never send** (confirmed v1 to v2 regression).
6. **Cost periods rest on a false refill** created by the May to July 2026 sensor flapping.
7. **The backend logs nothing**, which slows every investigation.

## Hard rules

- **No doxing. The repo is PUBLIC.** The owner's postcode, email domain, and anything else that locates the household never go in code, tests, fixtures, docs, commit messages or PR text. Tests use the postcode `ZZ99 9ZZ` and the domain `example.net`. Recorded supplier responses are scrubbed before commit.
- KeroTrack never places an order and never submits a supplier form that needs an email address.
- Existing MQTT keys keep their names and types. New information goes in new keys or topics.
- The security contract in `CLAUDE.md` applies: new `/api` routes need auth, mutating routes need CSRF, the postcode setting is `is_secret=True`, no RFC 1918 literals in the repo.

## Owner decisions

1. **Trigger** is an **effective price per litre** (value), not a total for a quantity. 500 L is every supplier's minimum.
2. **Reserve:** 100 L, the minimum acceptable level, counts as empty.
3. **Lead time:** 14 days, plus 7 when the window overlaps December to February. Only the default, non urgent delivery is considered; faster delivery is the owner's call at order time.
4. **Email:** parked. Only suppliers that quote without an email are in scope.

## Part A: Analysis fixes

### A1. Logging

There is no `logging.basicConfig`/`dictConfig` anywhere; `bootstrap.py` declares `log_level` and nothing reads it, so app INFO logs are discarded. Configure root logging at startup from `Bootstrap.log_level` (format `%(asctime)s %(levelname)s %(name)s: %(message)s`, stderr), idempotently, without breaking uvicorn's own loggers.

### A2. Notifier never fires

`schedule.*_cron` defaults are `0 6/7/8 * * 0`, written meaning crontab Sunday. APScheduler's `CronTrigger.from_crontab` treats `0` as **Monday** (`WEEKDAYS = ["mon", ...]`). The notifier's predicate `is_weekly_run_day` checks `now.weekday() == 6` (Sunday), so the Monday run always skips. v1 called the notifier **daily** and let the predicate choose the day.

Fix:
- `schedule.notifier_cron` default `0 8 * * *` (daily; the predicate picks Sunday, as in v1).
- `schedule.analysis_cron` default `0 6 * * sun`, `schedule.cost_analysis_cron` default `0 7 * * sun` (names, never numbers).
- A **settings value migration** at startup: rewrite a stored value only when it equals the old default exactly (`0 6 * * 0` to `0 6 * * sun`, `0 7 * * 0` to `0 7 * * sun`, `0 8 * * 0` to `0 8 * * *`). Customised values are left alone. Each rewrite is recorded in `setting_changes` with source `migration`.
- **Seam test:** build each shipped default with `CronTrigger.from_crontab` and assert that for the notifier, some fire time in any 7 day window satisfies `is_weekly_run_day`; and that the analysis and cost triggers fire on a Sunday.

### A3. Hot water from a schedule

The sensor reads in whole centimetres (about 13 L each in this tank), so it often can't see hot water use. The logic must count it anyway.

- `boiler.hw_schedule` (json): list of slots `{"days": ["mon", ...], "start": "HH:MM", "hours": 1.0}`. Default reproduces today's 10 slots a week: one slot daily, plus a second on Friday, Saturday and Sunday.
- `boiler.hw_burner_minutes_per_slot` (float, default 33.0, which reproduces today's 1.83 L/day so upgrading changes nothing until calibrated).
- Litres per slot = minutes ÷ 60 × `boiler.fuel_rate_l_per_h`. Daily figure for a date = sum over slots whose `days` include that weekday. The analysis uses the weekly average.
- Replaces `HW_SESSIONS_PER_WEEK`, `HW_SESSION_HOURS`, `HW_BUFFER_FACTOR`.

### A4. Day bucketing and calibration

Shared by A5, Part C and calibration:

- `daily_usage(readings, refill_threshold_l)` turns trusted readings into one row per calendar day: litres used (sum of positive pair drops, refills skipped), with the per pair walk done inside a day so short gaps can't extrapolate. Days touching a refill (manual log date ±1 day or a sensor refill flag) are excluded.
- **Calibration** fits `daily_used ≈ hw_l_per_day + k × hdd` by least squares over trusted days in the last 400 days. Fixing `hw_l_per_day` at the schedule value gives `k`; the free fit also proposes burner minutes. Output: `k`, proposed burner minutes, mean absolute error, days used. A month level fit on 2025-05 to 2026-05 gave about 0.13 to 0.19 L/HDD and 9 to 14 minutes. Results are **proposals**: `POST /api/buying/calibrate` returns them and never writes settings.
- `k` is stored per run (Part C table). If a fit fails (fewer than 30 heating days) the last good `k` is used, else a default of 0.16.
- **HDD comes from the tank sensor's temperature** (`ingest/recalc.py`), not outdoor air. `k` is calibrated on the same signal; never mix in an external HDD source.

### A5. Heating estimate replaced

Replace the old 7 day/long blend and its 0.5 to 15 clamp with `k × today's HDD` (0 when HDD is 0). Publish an extra key `heating_estimate_basis` = `"model"` on `oiltank/analysis`.

### A6. Runway keys made honest

`estimated_days_remaining`, `estimated_empty_date`, `remaining_days_empty_hdd` and `remaining_date_empty_hdd` come from the `normal` runway projection (Part C) to the reserve level, instead of the flat rate. Same keys and types. If the projection can't run, fall back to the old calculation.

### A7. Cost periods anchored on the refill log

Cost periods are currently split at sensor `refill_detected == "y"` readings (`analysis/cost.py`). The flapping produced a false refill on 2026-07-30, and the real 2025-05-07 refill was noise suppressed, so one bogus period runs 2024-10-10 to 2026-07-30 (657 days, 278 L).

Fix: period boundaries come from `actual_refill_costs.refill_date` (authoritative). A sensor refill flag becomes a boundary only when there is no manual entry within 7 days of it **and** the flagged reading is trusted **and** the level stays up for 24 h afterwards. Stale `refill_periods` rows that no longer match a boundary pair are deleted on the next cost run, so the normal job rebuilds the table. DB backup before deploy.

### A8. `days_since_refill` collision

`oiltank/cost_analysis` publishes `days_since_refill` counted from the period end; `oiltank/analysis` counts from the refill. Add `days_since_period_end` to the cost payload, and keep `days_since_refill` on the cost payload with the **same meaning as analysis** (days from the last refill date), so both topics agree. Update `frontend/src/lib/types/api.ts`.

### Database column additions

`create_all` never alters tables. Add a small `ensure_columns(conn, table, {column: type})` step in `db_migrate.py` (SQLite `PRAGMA table_info`, then `ALTER TABLE ... ADD COLUMN`), idempotent. Used for `analysis_results.heating_estimate_basis` (TEXT) and `cost_analysis.days_since_period_end` (INTEGER).

## Part B: Supplier quotes

### Provider model

New package `kerotrack/quotes/`:

```python
@dataclass(frozen=True, slots=True)
class QuoteRequest:
    postcode: str
    litres: int
    tanker: str  # "standard" | "small" | "baby"

@dataclass(frozen=True, slots=True)
class QuoteOption:
    supplier: str
    litres: int
    delivery_by: str | None      # ISO date
    delivery_label: str | None   # "Standard", "Express", ...
    urgent: bool                 # express, next day, Saturday, Sunday
    ppl_net: float | None        # as stated by the supplier, ex VAT, pence
    total_inc_vat: float         # all in: fees and VAT included, pounds
    fees_inc_vat: float

class QuoteProvider(Protocol):
    name: str
    async def fetch(self, client: httpx.AsyncClient, req: QuoteRequest) -> list[QuoteOption]: ...
```

**Effective price** = `total_inc_vat / 1.05 / litres × 100` (pence per litre ex VAT, fees included). Every comparison and display uses it.

Endpoints are constants in each provider module, never settings, so there is no user supplied URL and no SSRF surface.

### Providers

- **`homefuelsdirect`** (in scope): GET `https://homefuelsdirect.co.uk/index.php?option=com_virtuemart&view=cart&task=locateJS&format=json&ftype=1&customer_uniqid=&customer_county=&pcode=<pc>&qty=<n>&async=true`. JSON with `prices.Window1..N`, each `{ppl_total_net (pounds per litre), orderTotal, vatTotal, orderTotalNet}`; windows priced `0.00` are skipped. The payload carries no dates, so `delivery_by` is null and windows are labelled `Window1..N`. The **last** non zero window is treated as the default non urgent option (the site lists quickest to cheapest; all four were equal on 2026-10-04); the others are marked `urgent=True`. No fees.
- **BoilerJuice national index:** the existing scraper stays, recorded as `kind="index"`.
- **yournrg:** retired. `prices.yournrg_url` goes into `RETIRED_KEYS`; scraper code and its fallback are removed.
- Parked (need an email): The Heating Oil Company, NWF, Western Fuel.

Politeness: polls twice daily, `User-Agent: KeroTrack/2 (+https://github.com/MrSiJo/KeroTrack)`, one attempt plus one retry per provider per poll.

### Storage

New table `price_quotes`: `id` int PK, `fetched_at` text, `supplier` text, `kind` text (`quote`/`index`), `litres` int, `delivery_by` text null, `delivery_label` text null, `urgent` int, `ppl_net` float null, `total_inc_vat` float null, `fees_inc_vat` float, `ppl_effective` float null, `ok` int, `error` text null. Failed polls write an `ok=0` row. Keep all rows.

### current_ppl

`PriceService.current_ppl()` prefers the cheapest **non urgent** quote fetched within 36 h (its effective price), falling back to the BoilerJuice index. `price_cache.json` keeps its existing keys.

### Settings (new groups `buying` and `projection`)

| Key | Type | Default |
|---|---|---|
| `buying.postcode` | secret | `""` (empty disables quoting) |
| `buying.order_litres` | int | 500 |
| `buying.min_order_litres` | int | 500 |
| `buying.tanker` | string | `standard` |
| `buying.providers` | json | `["homefuelsdirect"]` |
| `buying.trigger_ppl` | float | 0.0 (off) |
| `buying.safe_fill_pct` | float | 0.95 |
| `buying.warn_days` | int | 14 |
| `buying.lead_time_days` | int | 14 |
| `buying.winter_lead_extra_days` | int | 7 |
| `projection.reserve_l` | float | 100.0 |
| `projection.active_scenario` | string | `normal` |
| `projection.scenarios` | json | see Part C |
| `schedule.buying_cron` | cron | `0 7,13 * * *` |

`buying` and `projection` are added to `GroupName` and to the frontend settings nav.

## Part C: Seasonal runway and order by date

Runs in a new daily `buying` job (with the quotes), not the weekly analysis.

```
litres[d+1] = litres[d] - hw_l(d) - k × expected_hdd(d) × multiplier(scenario, month(d))
```

- Start: latest trusted `litres_remaining`. Horizon 365 days.
- `hw_l(d)`: the A3 schedule for that weekday.
- `expected_hdd(d)`: mean HDD for the same month and day ±7 days across every year in `hdd_data`; where fewer than 2 years cover a date, that calendar month's mean over all data; no data at all means 0.
- `projection.scenarios` default:
  ```json
  {"normal": {}, "mild_then_cold": {"11": 0.8, "12": 0.8, "1": 0.8, "2": 1.5}, "cold": {"11": 1.3, "12": 1.3, "1": 1.3, "2": 1.3, "3": 1.3}}
  ```
  Multipliers touch the heating term only. Every scenario is computed.
- **Run out date** = the first day the level is at or below `projection.reserve_l`; null if not within the horizon.
- **Order by date** = run out − `buying.lead_time_days` − (`buying.winter_lead_extra_days` if any day in that lead window falls in December to February). Null when run out is null.
- **After order line:** the `normal` projection restarted at the order by date with `min_order_litres` added, giving the following order by date.
- Table `runway_projection`: `id`, `run_at`, `scenario`, `k`, `hw_l_per_day`, `start_litres`, `run_out_date`, `order_by_date`, `next_order_by_date` (normal only), `series_json` (list of `[date, litres]`, weekly points).

## Part D: Buy signal

Computed at the end of each `buying` run.

- **Best quote:** cheapest `total_inc_vat` among the latest poll's non urgent, `ok` quotes.
- **Headroom:** `tank.capacity_l × buying.safe_fill_pct − litres_remaining`.
- **States, in priority order:**

| State | Condition |
|---|---|
| `no_room` | headroom < `buying.min_order_litres` |
| `overdue` | today > active scenario's order by date |
| `deadline` | order by within `buying.warn_days` days |
| `buy_now` | `trigger_ppl` > 0 and best effective price ≤ trigger |
| `wait` | a best quote or index exists |
| `unknown` | no fresh quote (36 h) and no index |

- **Context (display only):** index percentile against the last 365 days of `readings.current_ppl`; 30 day change of the best effective price; today's spread between suppliers.
- **Outputs:** retained MQTT topic `oiltank/buying` (`state`, `best_total`, `best_supplier`, `best_ppl_effective`, `trigger_ppl`, `headroom_l`, `order_by`, `run_out`, `scenario`, `fetched_at`); `GET /api/buying/summary` (adds every scenario and the context); `GET /api/buying/quotes?days=90`; `POST /api/buying/run` (CSRF; runs the job now); `POST /api/buying/calibrate` (CSRF; returns proposals).
- **Alert** through Apprise only on a **transition into** `buy_now`, `deadline` or `overdue`. The last alerted state is stored in a one row table `buying_state` so a restart doesn't resend. Uses a generic `send(urls, title, body)` factored out of the notifier.

## Part E: UI

A new `/buying` page (Svelte 5, ECharts via existing components), linked in the sidebar:

1. State banner: state, best total, supplier, effective price, order by date, headroom.
2. Quotes table: latest poll per supplier with total, effective price, fees, label, age; failures shown as failed.
3. Price history chart: the index plus the best local effective price, with the trigger as a horizontal line.
4. Runway chart: litres per scenario, reserve line, order by markers.
5. Calibration panel: current `k` and hot water figure, a Calibrate button that shows the proposal, and a link to Settings to accept it.

Dashboard: a small badge with the state and order by date, linking to `/buying`.

## Out of scope

Placing orders; email requiring suppliers; KeroTrack-Display changes; an MCP server; third party weather forecasts; `analysis_data` being a JSON string; the thin cost base.

## Build order

1. A1 logging, A2 notifier (with the settings value migration and the generic Apprise `send`), `ensure_columns`.
2. A3 hot water schedule, A4 day bucketing and calibration.
3. Part C runway and order by, A5, A6.
4. A7 cost periods, A8 rename.
5. Part B quotes, `current_ppl`, yournrg retired.
6. Part D signal, MQTT, API, alerts.
7. Part E UI.
8. Deploy (backup first) and verify against live data.

## Evidence (2026-10-04)

Quotes for 500 L, standard tanker, all in inc VAT: Western Fuel £570.76, Home Fuels Direct £577.71 (110.04p ex VAT, no fees), The Heating Oil Company £587.27 (111.86p), BoilerJuice £587.70 (109.47p + £12.98 fee), NWF £635.62 (121.07p), yournrg no delivery. National index 108.29p.

Monthly use vs sensor HDD (clean months): 2025-06 to 09: 31, 10, 26, 24 L on 48, 19, 45, 124 HDD; 2025-10 to 2026-01: 34, 45, 60, 92 L on 177, 248, 316, 361; 2026-02 to 05: 64, 63, 46, 29 L on 250, 260, 192, 121. Free fit 0.29 L/day + 0.19 L/HDD (MAE 7.4 L/month).
