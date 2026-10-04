# Buy Planner and Analysis Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real supplier quotes, a seasonal runway with an order by date, a buy signal with alerts, and the analysis fixes (logging, notifier, hot water schedule, heating estimate, runway keys, cost periods).

**Architecture:** Pure logic lives in small new modules with no DB access (`analysis/hot_water.py`, `analysis/daily_usage.py`, `projection/runway.py`, `quotes/`, `buying/signal.py`). Thin DB facing services (`projection/service.py`, `quotes/store.py`, `buying/service.py`) load data, call the pure modules, persist, publish. A new daily `buying` scheduler job runs quotes, projection and signal; the weekly analysis reuses the projection for its runway keys.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async + aiosqlite, APScheduler 3, httpx + respx, pytest-asyncio (auto mode); SvelteKit (Svelte 5), Tailwind, ECharts, vitest.

**Spec:** `docs/superpowers/specs/2026-10-04-buy-planner-design.md`

## Progress (resume point)

Update after every wave. If a session dies, resume from the first unchecked task. Branch: `feat/buy-planner`.

| Task | Status | Commit |
|---|---|---|
| Spec | done | 02aa79a |
| Plan | done | c214fce |
| W1 T1 logging | done | 0914ac7 |
| W1 T3 ensure_columns | done | 3607a8a |
| W1 T4 settings catalogue | done | d04d547 |
| W1 T5 hot_water | done | fdd9408 |
| W1 T6 daily_usage + calibrate | done | faa78aa |
| W1 T7 runway | done | 6ba0034 |
| W1 T8 quotes package | done | 3474883 |
| W1 T9 signal | done | 3c56778 |
| W2 T2 notifier fix + send | done | e08a056 |
| W2 T10 cost periods + days_since | done | 69c483e |
| W2 T11 projection service + consumption | done | f169bfc |
| W3 T12 quotes store + price service + yournrg retired | todo | |
| W4 T13 buying job + MQTT + alerts | todo | |
| W5 T14 buying API | todo | |
| W6 T15 frontend | todo | |
| Final review | todo | |
| Local DB rehearsal | todo | |
| Deploy (backup first) | todo | |

Notes log (append, newest last):
- 2026-10-04: baseline backend 336 passed. gitleaks is blocked on Windows by App Control; commit from WSL (`scratchpad/wslcommit.sh`, hooks via `core.hooksPath=~/kt-hooks`). Never `--no-verify`.
- 2026-10-04 late: Wave 1 complete, all 8 reviewed and approved, suite 392 passed. Next: Wave 2 (T2, T10, T11) in parallel.
- 2026-10-05 early: Wave 2 complete (T10 took 3 fix rounds: refill log dates lag the real jump by ~12 days, so boundaries snap to the confirmed jump). Suite 425 passed. Next: T12.

## Global Constraints

- **No doxing (PUBLIC repo):** never write the owner's postcode, email domain or any locating detail. Tests use postcode `ZZ99 9ZZ` and domain `example.net`.
- New `/api` routes require auth; mutating routes are CSRF checked (automatic via middleware; `tests/api/test_security_invariants.py` enumerates every route).
- `buying.postcode` is `is_secret=True`.
- No RFC 1918 IP literals anywhere (pre-commit hook).
- Existing MQTT keys keep names and types; only add keys/topics.
- Dates in the DB are local naive ISO strings `YYYY-MM-DD HH:MM:SS` (see `kerotrack/clock.py`: `local_now`, `local_now_str`, `parse_local`).
- Subagents do **not** commit. The controller commits per task from WSL.
- Run backend tests with `backend/.venv/Scripts/python.exe -m pytest` from `backend/`.
- Effective price = `total_inc_vat / 1.05 / litres * 100` (pence/L ex VAT, fees included).
- Reserve default 100 L; lead 14 days + 7 when the lead window touches Dec, Jan or Feb.

## Review Focus

1. **Flat sensor in summer:** readings unchanged for weeks must still produce a hot water draw in the projection every day (T7, T11 tests).
2. **Empty or missing data:** no `hdd_data`, fewer than 30 heating days, no readings, empty postcode: every service returns a defined fallback, never raises (T6, T7, T11, T13 tests).
3. **Supplier payload shape change:** HFD returns HTML, an error, or windows all `0.00`: provider returns `[]` with an error string, stored as `ok=0`, never a wrong number (T8 test).
4. **Restart mid state:** a restart must not resend an alert for an unchanged state (T13 test).
5. **Customised crons:** the settings value migration must leave a non default stored cron untouched (T2 test).

---

## Wave 1 (parallel, disjoint files)

### Task 1: Logging config (A1)  [model: haiku]

**Files:**
- Create: `backend/kerotrack/logging_config.py`
- Modify: `backend/kerotrack/main.py` (call at the top of `lifespan`)
- Test: `backend/tests/unit/test_logging_config.py`

**Interfaces:** Produces `configure_logging(level: str) -> None`.

- [ ] **Step 1: failing test**

```python
import logging
from kerotrack.logging_config import configure_logging, _HANDLER_NAME

def test_configure_logging_sets_level_and_single_handler():
    configure_logging("DEBUG")
    configure_logging("INFO")  # idempotent
    root = logging.getLogger()
    ours = [h for h in root.handlers if getattr(h, "name", None) == _HANDLER_NAME]
    assert len(ours) == 1
    assert root.level == logging.INFO
    assert logging.getLogger("kerotrack.scheduler.service").getEffectiveLevel() == logging.INFO

def test_configure_logging_bad_level_falls_back_to_info():
    configure_logging("NOPE")
    assert logging.getLogger().level == logging.INFO
```

- [ ] **Step 2:** run `python -m pytest tests/unit/test_logging_config.py -q`, expect ImportError.
- [ ] **Step 3: implement**

```python
"""Root logging setup so kerotrack.* INFO logs reach stderr under uvicorn."""

from __future__ import annotations

import logging
import sys

_HANDLER_NAME = "kerotrack-root"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str) -> None:
    lvl = logging.getLevelName(str(level).upper())
    if not isinstance(lvl, int):
        lvl = logging.INFO
    root = logging.getLogger()
    root.setLevel(lvl)
    for h in root.handlers:
        if getattr(h, "name", None) == _HANDLER_NAME:
            h.setLevel(lvl)
            return
    handler = logging.StreamHandler(sys.stderr)
    handler.name = _HANDLER_NAME
    handler.setLevel(lvl)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
```

In `main.py` `lifespan`, right after the `Bootstrap` object (`boot`) is created: `configure_logging(boot.log_level)`. Read `main.py` first to find where `boot` is built.

- [ ] **Step 4:** tests pass; full suite still green.

### Task 3: ensure_columns + new columns  [model: haiku]

**Files:**
- Modify: `backend/kerotrack/db_migrate.py`, `backend/kerotrack/models/analysis_result.py`, `backend/kerotrack/models/cost_analysis.py`
- Test: `backend/tests/unit/test_db_migrate_columns.py`

**Interfaces:** Produces `async def ensure_columns(conn, table: str, columns: dict[str, str]) -> list[str]` (returns added column names). `ensure_schema` calls it for `analysis_results: {"heating_estimate_basis": "TEXT"}` and `cost_analysis: {"days_since_period_end": "INTEGER"}`. Model attributes: `AnalysisResult.heating_estimate_basis: Mapped[str | None]`, `CostAnalysis.days_since_period_end: Mapped[int | None]` (nullable).

- [ ] **Step 1: failing test**

```python
import sqlite3
from sqlalchemy import text
from kerotrack.db import init_engine
from kerotrack.db_migrate import ensure_schema

async def test_ensure_schema_adds_missing_columns_to_old_tables(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE analysis_results (latest_reading_date TEXT PRIMARY KEY)")
    con.execute("CREATE TABLE cost_analysis (analysis_date TEXT PRIMARY KEY)")
    con.commit(); con.close()
    eng = init_engine(f"sqlite+aiosqlite:///{db.as_posix()}")
    await ensure_schema(eng)
    await ensure_schema(eng)  # idempotent
    async with eng.connect() as conn:
        cols = [r[1] for r in (await conn.execute(text("PRAGMA table_info(analysis_results)"))).all()]
        assert "heating_estimate_basis" in cols
        cols = [r[1] for r in (await conn.execute(text("PRAGMA table_info(cost_analysis)"))).all()]
        assert "days_since_period_end" in cols
    await eng.dispose()
```

- [ ] **Step 2:** run, expect failure.
- [ ] **Step 3: implement** in `db_migrate.py`:

```python
from sqlalchemy import text

_COLUMN_ADDITIONS: dict[str, dict[str, str]] = {
    "analysis_results": {"heating_estimate_basis": "TEXT"},
    "cost_analysis": {"days_since_period_end": "INTEGER"},
}
_ALLOWED_TYPES = {"TEXT", "INTEGER", "REAL", "FLOAT"}


async def ensure_columns(conn, table: str, columns: dict[str, str]) -> list[str]:
    if not table.isidentifier():
        raise ValueError(f"bad table name {table!r}")
    existing = {r[1] for r in (await conn.execute(text(f"PRAGMA table_info({table})"))).all()}  # nosec B608  # noqa: S608
    added: list[str] = []
    for name, col_type in columns.items():
        if name in existing:
            continue
        if not name.isidentifier() or col_type not in _ALLOWED_TYPES:
            raise ValueError(f"bad column spec {name} {col_type}")
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"))  # nosec B608  # noqa: S608
        added.append(name)
    return added
```

and in `ensure_schema`, after `create_all`, inside the same `engine.begin()` block: loop `_COLUMN_ADDITIONS` and `await ensure_columns(conn, t, cols)`. Note `conn` there is an `AsyncConnection`. Add the two nullable mapped columns to the models.

- [ ] **Step 4:** tests pass; full suite green (existing analysis/cost tests must still persist payloads; the new columns are nullable and absent from payloads until later tasks).

### Task 4: Settings catalogue additions  [model: sonnet]

**Files:**
- Modify: `backend/kerotrack/settings/schema.py`, `backend/tests/unit/test_settings_schema.py` (update `EXPECTED_KEYS` / count)
- Test: `backend/tests/unit/test_settings_buying_keys.py`

**Interfaces:** Produces these catalogue keys (exact names, types, defaults):

| Key | type | group | default |
|---|---|---|---|
| `boiler.hw_schedule` | json | boiler | `[{"days": ["mon","tue","wed","thu","fri","sat","sun"], "start": "03:00", "hours": 1.0}, {"days": ["fri","sat","sun"], "start": "16:30", "hours": 1.0}]` |
| `boiler.hw_burner_minutes_per_slot` | float | boiler | `33.0` (min 0, max 60, step 0.5) |
| `buying.postcode` | secret | buying | `""` (`is_secret=True`) |
| `buying.order_litres` | int | buying | `500` |
| `buying.min_order_litres` | int | buying | `500` |
| `buying.tanker` | string | buying | `"standard"` |
| `buying.providers` | json | buying | `["homefuelsdirect"]` |
| `buying.trigger_ppl` | float | buying | `0.0` |
| `buying.safe_fill_pct` | float | buying | `0.95` |
| `buying.warn_days` | int | buying | `14` |
| `buying.lead_time_days` | int | buying | `14` |
| `buying.winter_lead_extra_days` | int | buying | `7` |
| `projection.reserve_l` | float | projection | `100.0` |
| `projection.active_scenario` | string | projection | `"normal"` |
| `projection.scenarios` | json | projection | `{"normal": {}, "mild_then_cold": {"11": 0.8, "12": 0.8, "1": 0.8, "2": 1.5}, "cold": {"11": 1.3, "12": 1.3, "1": 1.3, "2": 1.3, "3": 1.3}}` |
| `schedule.buying_cron` | cron | schedule | `"0 7,13 * * *"` |
| `mqtt.topic_buying` | string | mqtt | `"oiltank/buying"` |

Also change defaults: `schedule.analysis_cron` → `"0 6 * * sun"`, `schedule.cost_analysis_cron` → `"0 7 * * sun"`, `schedule.notifier_cron` → `"0 8 * * *"`, and replace the misleading comment above them with one explaining APScheduler treats `0` as Monday so names are used, and that the notifier runs daily and its predicate picks Sunday. Add `"buying"` and `"projection"` to `GroupName`. Give each new key a short `label` and `description`.

- [ ] **Step 1: failing test**

```python
from kerotrack.settings.schema import SETTINGS_CATALOGUE

def test_buying_keys_present_with_defaults():
    c = SETTINGS_CATALOGUE
    assert c["buying.postcode"].is_secret is True
    assert c["buying.order_litres"].default == 500
    assert c["projection.reserve_l"].default == 100.0
    assert c["schedule.buying_cron"].default == "0 7,13 * * *"
    assert c["schedule.notifier_cron"].default == "0 8 * * *"
    assert c["schedule.analysis_cron"].default == "0 6 * * sun"
    assert c["boiler.hw_burner_minutes_per_slot"].default == 33.0
    assert set(c["projection.scenarios"].default) == {"normal", "mild_then_cold", "cold"}
```

(Check how `SETTINGS_CATALOGUE` is keyed by reading `schema.py`; adapt the lookup if it's a list.)
- [ ] **Step 2:** fails. **Step 3:** implement. **Step 4:** whole suite green (fix `EXPECTED_KEYS`, and any test that pinned the old cron defaults, e.g. `test_notifier.py` or `test_settings_*`; adjust expectations, do not delete coverage).

### Task 5: Hot water schedule (A3 pure)  [model: haiku]

**Files:** Create `backend/kerotrack/analysis/hot_water.py`; Test `backend/tests/unit/test_hot_water.py`

**Interfaces:** Produces:
- `WEEKDAYS: tuple[str, ...] = ("mon","tue","wed","thu","fri","sat","sun")` (index = Python `weekday()`)
- `validate_schedule(raw: object) -> list[dict]` (raises `ValueError`)
- `slots_per_weekday(schedule: list[dict]) -> dict[int, float]` (weekday → total slot hours)
- `hw_litres_for_weekday(schedule, weekday: int, burner_minutes: float, fuel_rate_l_per_h: float) -> float`
- `hw_litres_per_day_avg(schedule, burner_minutes, fuel_rate_l_per_h) -> float`
- `slots_per_week(schedule) -> float` (sum of slot hours over the week, slot hours normalised to 1 h units)

Burner minutes are **per 1 hour slot**; a slot with `hours: 2.0` counts double.

- [ ] **Step 1: failing tests**

```python
import pytest
from kerotrack.analysis.hot_water import (
    validate_schedule, slots_per_weekday, hw_litres_for_weekday,
    hw_litres_per_day_avg, slots_per_week,
)

DEFAULT = [
    {"days": ["mon","tue","wed","thu","fri","sat","sun"], "start": "03:00", "hours": 1.0},
    {"days": ["fri","sat","sun"], "start": "16:30", "hours": 1.0},
]

def test_default_reproduces_legacy_183():
    assert hw_litres_per_day_avg(DEFAULT, 33.0, 2.33) == pytest.approx(1.8307, abs=1e-3)

def test_weekday_split():
    per = slots_per_weekday(DEFAULT)
    assert per[0] == 1.0 and per[4] == 2.0 and per[6] == 2.0
    assert hw_litres_for_weekday(DEFAULT, 5, 15.0, 2.33) == pytest.approx(2 * 15 / 60 * 2.33)
    assert slots_per_week(DEFAULT) == 10.0

def test_validate_rejects_bad_day_and_hours():
    with pytest.raises(ValueError):
        validate_schedule([{"days": ["funday"], "start": "03:00", "hours": 1}])
    with pytest.raises(ValueError):
        validate_schedule([{"days": ["mon"], "start": "03:00", "hours": -1}])
    with pytest.raises(ValueError):
        validate_schedule("nope")

def test_empty_schedule_is_zero():
    assert hw_litres_per_day_avg([], 33.0, 2.33) == 0.0
```

- [ ] **Step 3: implement**

```python
"""Hot water draw from the owner's boiler schedule (spec A3).

The tank sensor reads in ~13 L steps, so it often cannot see hot water use.
The schedule says when the boiler heats water; the burner fires for
``burner_minutes`` of each 1 h slot at ``fuel_rate_l_per_h``.
"""

from __future__ import annotations

import re

WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def validate_schedule(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("hw_schedule must be a list of slots")
    out: list[dict] = []
    for slot in raw:
        if not isinstance(slot, dict):
            raise ValueError("each slot must be an object")
        days = slot.get("days")
        if not isinstance(days, list) or not days or any(d not in WEEKDAYS for d in days):
            raise ValueError(f"bad days in slot {slot!r}")
        start = str(slot.get("start", "00:00"))
        if not _HHMM.match(start):
            raise ValueError(f"bad start time {start!r}")
        hours = slot.get("hours", 1.0)
        if not isinstance(hours, (int, float)) or hours <= 0 or hours > 24:
            raise ValueError(f"bad hours {hours!r}")
        out.append({"days": list(days), "start": start, "hours": float(hours)})
    return out


def slots_per_weekday(schedule: list[dict]) -> dict[int, float]:
    per = {i: 0.0 for i in range(7)}
    for slot in validate_schedule(schedule):
        for d in slot["days"]:
            per[WEEKDAYS.index(d)] += slot["hours"]
    return per


def slots_per_week(schedule: list[dict]) -> float:
    return sum(slots_per_weekday(schedule).values())


def hw_litres_for_weekday(
    schedule: list[dict], weekday: int, burner_minutes: float, fuel_rate_l_per_h: float
) -> float:
    hours = slots_per_weekday(schedule)[weekday]
    return hours * (burner_minutes / 60.0) * fuel_rate_l_per_h


def hw_litres_per_day_avg(
    schedule: list[dict], burner_minutes: float, fuel_rate_l_per_h: float
) -> float:
    return slots_per_week(schedule) * (burner_minutes / 60.0) * fuel_rate_l_per_h / 7.0
```

- [ ] **Step 4:** pass.

### Task 6: Daily usage bucketing + calibration (A4 pure)  [model: sonnet]

**Files:** Create `backend/kerotrack/analysis/daily_usage.py`; Test `backend/tests/unit/test_daily_usage.py`

**Interfaces:** Produces:

```python
@dataclass(frozen=True, slots=True)
class Point:
    when: datetime
    litres: float

@dataclass(frozen=True, slots=True)
class DayUsage:
    day: date
    used_l: float   # may be negative (sensor noise); noise cancels in the fit

@dataclass(frozen=True, slots=True)
class Calibration:
    k: float | None                 # L per HDD with hw fixed at the schedule figure
    hw_fixed_l: float
    free_hw_l: float | None         # intercept of the free fit
    free_k: float | None
    proposed_burner_minutes: float | None
    mae_l: float | None             # mean abs error of the fixed-hw model, L/day
    days_used: int
    heating_days: int

def bucket_daily(points: list[Point], *, max_abs_daily_l: float, exclude_days: set[date]) -> list[DayUsage]
def calibrate(days: list[DayUsage], hdd_by_day: dict[date, float], *, hw_l_per_day: float,
              slots_per_week: float, fuel_rate_l_per_h: float, min_heating_days: int = 30) -> Calibration
```

Algorithm:
- `bucket_daily`: group points by calendar date; level(day) = median of that day's litres. For consecutive calendar days (d-1, d) both present: `used = level(d-1) - level(d)`. Drop the day if `d` or `d-1` is in `exclude_days`, or `abs(used) > max_abs_daily_l`. Non consecutive days are skipped (no interpolation). Sorted by day.
- `calibrate`: use days with an `hdd_by_day` entry. Fixed fit: `k = Σ((u - hw)·h) / Σ(h²)` over days where `h > 0`; `None` if fewer than `min_heating_days` such days. Free fit: ordinary least squares `u = a + b·h` over all days (needs ≥ 2 distinct `h` values), set `free_hw_l=a`, `free_k=b`; `proposed_burner_minutes = a * 7 * 60 / (slots_per_week * fuel_rate)` when `a > 0` and `slots_per_week > 0`, else `None`. `mae_l` = mean `|u - (hw + k·h)|` when `k` is not None. Round nothing (callers round).

- [ ] **Step 1: failing tests**

```python
from datetime import date, datetime, timedelta
import random
import pytest
from kerotrack.analysis.daily_usage import Point, DayUsage, bucket_daily, calibrate

def _series(days, start_l=900.0, hw=0.8, k=0.17, hdd=None, noise=0.0, seed=1):
    rnd = random.Random(seed); pts = []; level = start_l; d0 = date(2025, 10, 1)
    for i in range(days):
        d = d0 + timedelta(days=i); h = hdd(d) if hdd else 0.0
        for hour in (1, 7, 13, 19):
            pts.append(Point(datetime(d.year, d.month, d.day, hour), level + rnd.uniform(-noise, noise)))
        level -= hw + k * h
    return pts

def test_bucket_uses_daily_median_and_drops_big_jumps():
    pts = [Point(datetime(2025,1,1,h), 500) for h in (1,2,3)] + \
          [Point(datetime(2025,1,2,h), 498) for h in (1,2,3)] + \
          [Point(datetime(2025,1,3,h), 1100) for h in (1,2,3)]  # refill
    days = bucket_daily(pts, max_abs_daily_l=55, exclude_days=set())
    assert days == [DayUsage(date(2025,1,2), 2.0)]

def test_bucket_skips_gaps_and_excluded():
    pts = [Point(datetime(2025,1,1,1), 500), Point(datetime(2025,1,3,1), 490), Point(datetime(2025,1,4,1), 489)]
    assert bucket_daily(pts, max_abs_daily_l=55, exclude_days={date(2025,1,4)}) == []

def test_calibrate_recovers_known_k_and_hw():
    hdd = lambda d: 10.0 if d.month in (11, 12, 1, 2) else (3.0 if d.day % 2 else 0.0)
    pts = _series(200, hw=0.8, k=0.17, hdd=hdd, noise=3.0)
    days = bucket_daily(pts, max_abs_daily_l=55, exclude_days=set())
    hdd_map = {du.day: hdd(du.day) for du in days}
    cal = calibrate(days, hdd_map, hw_l_per_day=0.8, slots_per_week=10, fuel_rate_l_per_h=2.33)
    assert cal.k == pytest.approx(0.17, abs=0.02)
    assert cal.free_hw_l == pytest.approx(0.8, abs=0.4)
    assert cal.proposed_burner_minutes == pytest.approx(0.8 * 7 * 60 / (10 * 2.33), rel=0.5)
    assert cal.heating_days >= 30

def test_calibrate_too_few_heating_days_gives_none():
    days = [DayUsage(date(2025,7,i), 0.8) for i in range(1, 20)]
    cal = calibrate(days, {d.day: 0.0 for d in days}, hw_l_per_day=0.8, slots_per_week=10, fuel_rate_l_per_h=2.33)
    assert cal.k is None and cal.mae_l is None
```

- [ ] **Step 3:** implement per the algorithm (use `statistics.median`; plain Python sums, no numpy).
- [ ] **Step 4:** pass.

### Task 7: Runway simulation (Part C pure)  [model: sonnet]

**Files:** Create `backend/kerotrack/projection/__init__.py` (empty), `backend/kerotrack/projection/runway.py`; Test `backend/tests/unit/test_runway.py`

**Interfaces:** Produces:

```python
@dataclass(frozen=True, slots=True)
class RunwayInputs:
    start_day: date
    start_litres: float
    k: float
    hw_by_weekday: dict[int, float]        # litres per weekday index 0..6
    expected_hdd: Callable[[date], float]
    multipliers: dict[int, float]          # month -> heating multiplier; missing = 1.0
    reserve_l: float
    horizon_days: int = 365

@dataclass(frozen=True, slots=True)
class RunwayResult:
    series: list[tuple[date, float]]       # daily, start_day first
    run_out: date | None

def parse_multipliers(raw: dict) -> dict[int, float]          # {"11": 0.8} -> {11: 0.8}; ignores bad keys
def climatology(hdd_by_day: dict[date, float], *, window_days: int = 7, min_years: int = 2) -> Callable[[date], float]
def simulate(inp: RunwayInputs) -> RunwayResult
def order_by_date(run_out: date | None, *, lead_days: int, winter_extra_days: int) -> date | None
def weekly_points(series: list[tuple[date, float]]) -> list[list]   # [[iso, litres_rounded_1dp], ...] every 7th day plus last
```

Rules:
- `simulate`: `litres = start_litres`; append `(start_day, litres)`; for i in 1..horizon: `d = start_day + i`; draw for the previous day `p = d - 1`: `hw_by_weekday[p.weekday()] + k * expected_hdd(p) * multipliers.get(p.month, 1.0)`; `litres -= draw`; append `(d, litres)`. `run_out` = first date with `litres <= reserve_l` (could be `start_day` if already at/below). Negative draws are clamped to 0.
- `climatology`: for target `d`, collect `hdd_by_day[x]` for every `x` whose month/day falls within ±window_days of `d`'s month/day **in any year** (compare by day of year with wraparound at 365/366; use `x.replace(year=d.year)` safe for Feb 29 by mapping to Feb 28). Count distinct years among matches; if ≥ `min_years` return the mean. Otherwise return the mean of all entries in the same calendar month across all years; if none, 0.0. Precompute lookup tables so a 365 day simulation is fast.
- `order_by_date`: `None` if run_out None. `cand = run_out - lead_days`; if any date in `[cand, run_out]` has month in {12, 1, 2}: `cand -= winter_extra_days`.

- [ ] **Step 1: failing tests**

```python
from datetime import date, timedelta
import pytest
from kerotrack.projection.runway import (
    RunwayInputs, simulate, climatology, order_by_date, parse_multipliers, weekly_points,
)

FLAT_HW = {i: 1.0 for i in range(7)}

def test_flat_summer_still_draws_hot_water_daily():
    r = simulate(RunwayInputs(date(2026,6,1), 400.0, 0.17, FLAT_HW, lambda d: 0.0, {}, 100.0, 365))
    assert r.series[1][1] == pytest.approx(399.0)
    assert r.run_out == date(2026,6,1) + timedelta(days=300)

def test_heating_and_multiplier_only_touch_heating_term():
    base = simulate(RunwayInputs(date(2026,11,1), 1000.0, 0.2, FLAT_HW, lambda d: 10.0, {}, 0.0, 10))
    mild = simulate(RunwayInputs(date(2026,11,1), 1000.0, 0.2, FLAT_HW, lambda d: 10.0, {11: 0.5}, 0.0, 10))
    assert 1000.0 - base.series[1][1] == pytest.approx(3.0)
    assert 1000.0 - mild.series[1][1] == pytest.approx(2.0)

def test_already_below_reserve_runs_out_today():
    r = simulate(RunwayInputs(date(2026,1,1), 90.0, 0.1, FLAT_HW, lambda d: 0, {}, 100.0, 30))
    assert r.run_out == date(2026,1,1)

def test_climatology_same_window_multi_year_else_month_mean():
    data = {date(2024,1,10): 10.0, date(2025,1,12): 14.0, date(2025,3,1): 4.0}
    f = climatology(data)
    assert f(date(2027,1,11)) == pytest.approx(12.0)
    assert f(date(2027,3,20)) == pytest.approx(4.0)   # one year only -> month mean
    assert f(date(2027,7,1)) == 0.0

def test_order_by_adds_winter_extra_only_in_dec_to_feb():
    assert order_by_date(date(2027,2,28), lead_days=14, winter_extra_days=7) == date(2027,2,7)
    assert order_by_date(date(2027,6,30), lead_days=14, winter_extra_days=7) == date(2027,6,16)
    assert order_by_date(None, lead_days=14, winter_extra_days=7) is None

def test_parse_multipliers_and_weekly_points():
    assert parse_multipliers({"11": 0.8, "x": 2, "13": 1}) == {11: 0.8}
    s = [(date(2026,1,1) + timedelta(days=i), 100.0 - i) for i in range(10)]
    assert weekly_points(s) == [["2026-01-01", 100.0], ["2026-01-08", 93.0], ["2026-01-10", 91.0]]
```

- [ ] **Step 3:** implement. **Step 4:** pass.

### Task 8: Quotes package (Part B pure + provider)  [model: sonnet]

**Files:** Create `backend/kerotrack/quotes/__init__.py`, `quotes/models.py`, `quotes/homefuelsdirect.py`, `quotes/registry.py`; Tests `backend/tests/unit/test_quotes_models.py`, `backend/tests/unit/test_quotes_homefuelsdirect.py`, fixture `backend/tests/fixtures/hfd_quote.json`

**Interfaces:** Produces:
- `quotes.models`: `QuoteRequest(postcode: str, litres: int, tanker: str)`, `QuoteOption(supplier, litres, delivery_by: str|None, delivery_label: str|None, urgent: bool, ppl_net: float|None, total_inc_vat: float, fees_inc_vat: float)`, `effective_ppl(total_inc_vat: float, litres: int) -> float`, `best_option(options: list[QuoteOption]) -> QuoteOption | None` (non urgent, lowest total), `USER_AGENT = "KeroTrack/2 (+https://github.com/MrSiJo/KeroTrack)"`, `@dataclass PollResult(supplier: str, options: list[QuoteOption], error: str | None)`.
- `quotes.homefuelsdirect`: `class HomeFuelsDirect: name = "homefuelsdirect"`, `BASE_URL = "https://homefuelsdirect.co.uk/index.php"`, `def parse(self, payload: object, litres: int) -> list[QuoteOption]`, `async def fetch(self, client: httpx.AsyncClient, req: QuoteRequest) -> list[QuoteOption]` (raises on HTTP/JSON errors).
- `quotes.registry`: `PROVIDERS: dict[str, object] = {"homefuelsdirect": HomeFuelsDirect()}`, `async def poll(client, req, names: list[str]) -> list[PollResult]` (one try + one retry per provider; unknown names give `PollResult(name, [], "unknown provider")`; any exception gives `error=type(e).__name__ + ": " + str(e)[:120]`; an empty parse gives `error="no prices"`).

HFD request params (exact): `option=com_virtuemart, view=cart, task=locateJS, format=json, ftype=1, customer_uniqid="", customer_county="", pcode=<postcode>, qty=<litres>, async=true`, header `User-Agent: USER_AGENT`, timeout 15 s.

HFD parse: `payload["prices"]` dict of `WindowN` → `{"ppl_total_net": pounds/L, "orderTotal": £}`. Keep windows with `orderTotal > 0`, ordered by N. The **last** kept window is non urgent (`urgent=False`, label `"Standard"`); earlier ones `urgent=True`, label `"Faster (WindowN)"`. `ppl_net = round(ppl_total_net * 100, 2)`, `total_inc_vat = orderTotal`, `fees_inc_vat = 0.0`, `delivery_by = None`. Non dict payload or no `prices` → `[]`.

Fixture `hfd_quote.json` (scrubbed: postcode replaced):

```json
{"id": 1, "Postcode": "ZZ99 9", "Volume": 500, "county": "Testshire",
 "prices": {
  "Window1": {"ppl_total_gross": 1.15542, "ppl_total_net": 1.1004, "vatTotal": 27.51, "orderTotalNet": 550.2, "orderTotal": 577.71},
  "Window2": {"ppl_total_gross": 1.15542, "ppl_total_net": 1.1004, "vatTotal": 27.51, "orderTotalNet": 550.2, "orderTotal": 577.71},
  "Window3": {"ppl_total_gross": 1.1, "ppl_total_net": 1.05, "vatTotal": 26.25, "orderTotalNet": 525.0, "orderTotal": 551.25},
  "Window4": {"ppl_total_gross": 0, "ppl_total_net": 0, "vatTotal": 0, "orderTotalNet": 0, "orderTotal": 0}
 }}
```

- [ ] **Step 1: failing tests**

```python
# test_quotes_models.py
import pytest
from kerotrack.quotes.models import QuoteOption, effective_ppl, best_option

def _q(total, urgent=False, s="a"):
    return QuoteOption(s, 500, None, None, urgent, None, total, 0.0)

def test_effective_ppl_includes_fees_ex_vat():
    assert effective_ppl(587.70, 500) == pytest.approx(111.943, abs=1e-3)

def test_best_option_ignores_urgent_and_ranks_on_total():
    assert best_option([_q(570, urgent=True), _q(588, s="bj"), _q(578, s="hfd")]).supplier == "hfd"
    assert best_option([_q(570, urgent=True)]) is None
    assert best_option([]) is None
```

```python
# test_quotes_homefuelsdirect.py
import json, pathlib
import httpx, pytest, respx
from kerotrack.quotes.homefuelsdirect import HomeFuelsDirect
from kerotrack.quotes.models import QuoteRequest
from kerotrack.quotes.registry import poll

FIX = json.loads((pathlib.Path(__file__).parents[1] / "fixtures" / "hfd_quote.json").read_text())
REQ = QuoteRequest("ZZ99 9ZZ", 500, "standard")

def test_parse_skips_zero_windows_and_marks_last_non_urgent():
    opts = HomeFuelsDirect().parse(FIX, 500)
    assert [o.total_inc_vat for o in opts] == [577.71, 577.71, 551.25]
    assert [o.urgent for o in opts] == [True, True, False]
    assert opts[-1].ppl_net == 105.0

def test_parse_garbage_returns_empty():
    assert HomeFuelsDirect().parse("<html>", 500) == []
    assert HomeFuelsDirect().parse({"prices": {}}, 500) == []

@respx.mock
async def test_fetch_sends_postcode_qty_and_user_agent():
    route = respx.get("https://homefuelsdirect.co.uk/index.php").respond(json=FIX)
    async with httpx.AsyncClient() as c:
        opts = await HomeFuelsDirect().fetch(c, REQ)
    req = route.calls.last.request
    assert req.url.params["pcode"] == "ZZ99 9ZZ" and req.url.params["qty"] == "500"
    assert req.headers["User-Agent"].startswith("KeroTrack/2")
    assert len(opts) == 3

@respx.mock
async def test_poll_records_errors_not_numbers():
    respx.get("https://homefuelsdirect.co.uk/index.php").respond(status_code=500)
    async with httpx.AsyncClient() as c:
        res = await poll(c, REQ, ["homefuelsdirect", "nope"])
    assert res[0].options == [] and res[0].error
    assert res[1].error == "unknown provider"

@respx.mock
async def test_poll_html_body_is_no_prices():
    respx.get("https://homefuelsdirect.co.uk/index.php").respond(text="<html></html>")
    async with httpx.AsyncClient() as c:
        res = await poll(c, REQ, ["homefuelsdirect"])
    assert res[0].options == [] and res[0].error
```

- [ ] **Step 3:** implement (`fetch`: `r = await client.get(BASE_URL, params=..., headers=..., timeout=15.0)`, `r.raise_for_status()`, `return self.parse(r.json(), req.litres)`; JSON decode errors propagate so `poll` records them).
- [ ] **Step 4:** pass.

### Task 9: Buy signal state (Part D pure)  [model: haiku]

**Files:** Create `backend/kerotrack/buying/__init__.py` (empty), `backend/kerotrack/buying/signal.py`; Test `backend/tests/unit/test_buying_signal.py`

**Interfaces:** Produces:

```python
ALERT_STATES = frozenset({"buy_now", "deadline", "overdue"})

@dataclass(frozen=True, slots=True)
class SignalInputs:
    today: date
    headroom_l: float
    min_order_l: float
    order_by: date | None
    warn_days: int
    trigger_ppl: float
    best_ppl_effective: float | None
    has_index: bool

def compute_state(inp: SignalInputs) -> str
def should_alert(previous: str | None, current: str) -> bool
```

Priority: `no_room` (headroom < min order) → `overdue` (order_by and today > order_by) → `deadline` (order_by and (order_by - today).days <= warn_days) → `buy_now` (trigger > 0 and best not None and best <= trigger) → `wait` (best not None or has_index) → `unknown`. `should_alert` = current in ALERT_STATES and current != previous.

- [ ] **Step 1: failing tests** (table driven)

```python
from datetime import date
import pytest
from kerotrack.buying.signal import SignalInputs, compute_state, should_alert

T = date(2026, 10, 5)
def _i(**kw):
    base = dict(today=T, headroom_l=760, min_order_l=500, order_by=date(2027,1,20), warn_days=14,
                trigger_ppl=95.0, best_ppl_effective=110.0, has_index=True)
    base.update(kw); return SignalInputs(**base)

@pytest.mark.parametrize("kw,state", [
    (dict(headroom_l=400), "no_room"),
    (dict(order_by=date(2026,10,1)), "overdue"),
    (dict(order_by=date(2026,10,19)), "deadline"),
    (dict(best_ppl_effective=94.0), "buy_now"),
    (dict(trigger_ppl=0.0, best_ppl_effective=50.0), "wait"),
    (dict(), "wait"),
    (dict(best_ppl_effective=None, has_index=False), "unknown"),
    (dict(headroom_l=400, order_by=date(2026,10,1)), "no_room"),
    (dict(order_by=None, best_ppl_effective=None, has_index=True), "wait"),
])
def test_states(kw, state):
    assert compute_state(_i(**kw)) == state

def test_alert_only_on_transition_into_alert_states():
    assert should_alert("wait", "buy_now")
    assert not should_alert("buy_now", "buy_now")
    assert not should_alert("buy_now", "wait")
    assert should_alert(None, "deadline")
```

- [ ] **Step 3:** implement. **Step 4:** pass.

---

## Wave 2 (parallel, after Wave 1 merged)

### Task 2: Notifier fix, settings value migration, generic send (A2)  [model: sonnet]

**Files:**
- Create: `backend/kerotrack/notifier/send.py`
- Modify: `backend/kerotrack/settings/seeds.py` (value migration), `backend/kerotrack/notifier/apprise_notifier.py` (use `send.build_apprise`), wherever `seed_defaults` is invoked at startup (find with grep; call the migration right after it)
- Test: `backend/tests/unit/test_settings_value_migration.py`, `backend/tests/unit/test_scheduler_seam.py`, `backend/tests/unit/test_notifier_send.py`

**Interfaces:**
- Consumes: new cron defaults from Task 4.
- Produces: `seeds.DEFAULT_VALUE_REWRITES: dict[str, dict[str, str]]` = `{"schedule.analysis_cron": {"0 6 * * 0": "0 6 * * sun"}, "schedule.cost_analysis_cron": {"0 7 * * 0": "0 7 * * sun"}, "schedule.notifier_cron": {"0 8 * * 0": "0 8 * * *"}}`; `async def migrate_default_values(session) -> int` (rewrites stored JSON encoded values that equal an old value exactly, writes a `SettingChange` row with `source="migration"`, commits, returns count). `notifier.send`: `build_apprise(urls: list[str]) -> apprise.Apprise` (moved from `_build_apprise`, keep a `_build_apprise = build_apprise` alias in `apprise_notifier.py`), `async def send(urls: list[str], title: str, body: str, *, apprise_factory=None) -> bool` (returns False with no URLs; runs `notify` in `asyncio.to_thread`, markdown format).

Stored values are JSON encoded (`seeds._encode_default` uses `json.dumps`), so compare `json.loads(row.value)`.

- [ ] **Step 1: failing tests**

```python
# test_settings_value_migration.py
import json
from sqlalchemy import select
from kerotrack.models.setting import Setting
from kerotrack.models.setting_change import SettingChange
from kerotrack.settings.seeds import seed_defaults, migrate_default_values

async def test_rewrites_only_untouched_old_defaults(sf):
    async with sf() as s:
        await seed_defaults(s)
        rows = {r.key: r for r in (await s.execute(select(Setting))).scalars()}
        rows["schedule.analysis_cron"].value = json.dumps("0 6 * * 0")
        rows["schedule.notifier_cron"].value = json.dumps("0 8 * * 0")
        rows["schedule.cost_analysis_cron"].value = json.dumps("30 5 * * 2")  # customised
        await s.commit()
    async with sf() as s:
        assert await migrate_default_values(s) == 2
    async with sf() as s:
        rows = {r.key: json.loads(r.value) for r in (await s.execute(select(Setting))).scalars()}
        assert rows["schedule.analysis_cron"] == "0 6 * * sun"
        assert rows["schedule.notifier_cron"] == "0 8 * * *"
        assert rows["schedule.cost_analysis_cron"] == "30 5 * * 2"
        changes = (await s.execute(select(SettingChange).where(SettingChange.source == "migration"))).scalars().all()
        assert len(changes) == 2
    async with sf() as s:
        assert await migrate_default_values(s) == 0
```

```python
# test_scheduler_seam.py
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.triggers.cron import CronTrigger
from kerotrack.notifier.apprise_notifier import is_weekly_run_day
from kerotrack.settings.schema import SETTINGS_CATALOGUE

TZ = ZoneInfo("Europe/London")

def _fires(expr, start, days):
    trig = CronTrigger.from_crontab(expr, timezone=TZ)
    out, prev, now = [], None, start
    end = start + timedelta(days=days)
    while True:
        nxt = trig.get_next_fire_time(prev, now)
        if nxt is None or nxt > end:
            return out
        out.append(nxt); prev = nxt; now = nxt + timedelta(seconds=1)

def test_notifier_default_hits_a_sunday_every_week():
    expr = SETTINGS_CATALOGUE["schedule.notifier_cron"].default
    for offset in range(7):
        start = datetime(2026, 10, 5, tzinfo=TZ) + timedelta(days=offset)
        fires = _fires(expr, start, 7)
        assert any(is_weekly_run_day(f.replace(tzinfo=None)) for f in fires)

def test_weekly_jobs_fire_on_sunday():
    for key in ("schedule.analysis_cron", "schedule.cost_analysis_cron"):
        fires = _fires(SETTINGS_CATALOGUE[key].default, datetime(2026, 10, 5, tzinfo=TZ), 14)
        assert fires and all(f.weekday() == 6 for f in fires)

def test_buying_cron_fires_daily():
    fires = _fires(SETTINGS_CATALOGUE["schedule.buying_cron"].default, datetime(2026, 10, 5, tzinfo=TZ), 3)
    assert len(fires) == 6
```

```python
# test_notifier_send.py
from kerotrack.notifier.send import send

class _Fake:
    def __init__(self): self.calls = []
    def notify(self, **kw): self.calls.append(kw); return True

async def test_send_no_urls_is_false():
    assert await send([], "t", "b") is False

async def test_send_uses_factory():
    fake = _Fake()
    assert await send(["json://example.net"], "T", "B", apprise_factory=lambda urls: fake) is True
    assert fake.calls[0]["title"] == "T"
```

(Check `SETTINGS_CATALOGUE` indexing as in Task 4.)
- [ ] **Step 3:** implement; wire `migrate_default_values` immediately after the startup `seed_defaults` call.
- [ ] **Step 4:** full suite green.

### Task 10: Cost periods on the refill log + days_since (A7, A8)  [model: opus]

**Files:**
- Modify: `backend/kerotrack/analysis/cost.py`, `frontend/src/lib/types/api.ts` (add `days_since_period_end: number | null` to the cost analysis type)
- Test: `backend/tests/unit/test_cost_periods_manual.py` (and adjust `test_cost_analysis.py` only where it encoded the old sensor only behaviour)

**Interfaces:** Consumes `CostAnalysis.days_since_period_end` (Task 3). Produces `async def _period_boundaries(sf) -> list[str]` (sorted boundary timestamps) used by `_detect_periods`; the cost payload gains `days_since_period_end` and its `days_since_refill` now counts days from the latest `actual_refill_costs.refill_date` (fallback: latest accepted boundary).

Boundary rules (spec A7):
1. Every `actual_refill_costs.refill_date` is a boundary. Map it to the first trusted reading at/after that date (use the existing pattern from `consumption._first_trusted_reading_on_or_after`, query inline in cost.py) so the period starts on a real post refill level; if no such reading, skip it.
2. A sensor `refill_detected == "y"` reading is a boundary only if (a) no manual refill date within ±7 days, (b) the reading passes `trusted_readings_clause()`, and (c) every trusted reading in the following 24 h has `litres_remaining >= flagged.litres_remaining - refill_threshold_l`.
3. Sort and de duplicate (boundaries within 1 day of each other: keep the earlier).
4. After upserting periods, delete `refill_periods` rows whose `(start_date, end_date)` is not in the computed pairs.

Read `cost.py` fully first; keep `_per_pair_cost`, the actual cost matching and HDD metrics unchanged.

- [ ] **Step 1: failing test** (build data with the existing fixtures style in `test_cost_analysis.py`: insert `Reading` rows and `ActualRefillCost` rows into `sf`)

Scenario: readings every 12 h from 2025-01-01 to 2025-12-31 falling 1 L/12 h from 900; a real refill on 2025-05-07 (level jumps to 1100) that is flagged **noise_suppressed** (so `refill_detected` is not "y"; set `raw_flags` to the noise marker used by `trusted_readings_clause`, read `models/reading.py`) but logged in `ActualRefillCost(refill_date="2025-05-07 12:00:00", actual_volume_litres=500, actual_ppl=56.79, total_cost=298.0)`; a manual refill on 2025-01-01; and a false sensor refill flag on 2025-09-01 where the level jumps +150 then drops back within 6 h. Assert:
  - `_period_boundaries` returns exactly two boundaries, at/after 2025-01-01 and 2025-05-07;
  - after `_detect_periods`, `refill_periods` has exactly one row, starting at the first boundary and ending at the second;
  - a pre existing bogus row `(2025-05-07..., 2025-09-01...)` inserted before the run is deleted.
  - the cost payload `days_since_refill` equals days from 2025-05-07 to `now`, and `days_since_period_end` equals days from the period end.

Write the concrete test code following the helpers in `test_cost_analysis.py` (read it first). 
- [ ] **Step 2:** fails. **Step 3:** implement. **Step 4:** full suite green.

### Task 11: Projection service + consumption integration (A3, A5, A6, Part C wiring)  [model: opus]

**Files:**
- Create: `backend/kerotrack/projection/service.py`, `backend/kerotrack/models/runway_projection.py`
- Modify: `backend/kerotrack/db_migrate.py` (import the new model), `backend/kerotrack/analysis/consumption.py`
- Test: `backend/tests/unit/test_projection_service.py`, update `backend/tests/unit/test_consumption_analysis.py`

**Interfaces:**
- Consumes: `hot_water.*` (T5), `daily_usage.*` (T6), `runway.*` (T7), settings from T4, `heating_estimate_basis` column (T3).
- Produces:

```python
# models/runway_projection.py  (table "runway_projection")
class RunwayProjection(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[str]
    scenario: Mapped[str]
    k: Mapped[float]
    hw_l_per_day: Mapped[float]
    start_litres: Mapped[float]
    run_out_date: Mapped[str | None]
    order_by_date: Mapped[str | None]
    next_order_by_date: Mapped[str | None]
    series_json: Mapped[str]

# projection/service.py
DEFAULT_K = 0.16
@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    scenario: str
    run_out: date | None
    order_by: date | None
    next_order_by: date | None     # normal only, else None
    series: list[tuple[date, float]]

@dataclass(frozen=True, slots=True)
class ProjectionBundle:
    run_at: datetime
    start_litres: float
    k: float
    k_source: str                  # "fit" | "last_good" | "default"
    hw_l_per_day: float
    hw_by_weekday: dict[int, float]
    calibration: Calibration
    outcomes: dict[str, ScenarioOutcome]
    active_scenario: str

async def load_hw(svc) -> tuple[list[dict], float, float]          # schedule, burner_minutes, fuel_rate
async def run_calibration(sf, svc, *, now: datetime) -> Calibration
async def project(sf, svc, *, now: datetime | None = None) -> ProjectionBundle | None   # None if no trusted reading
async def persist_projection(sf, bundle: ProjectionBundle) -> None
```

`project` steps:
1. Latest trusted reading → `start_litres` (None bundle if missing).
2. Load trusted readings for the last 400 days → `Point`s; exclude days = manual refill dates ±1 day plus dates of `refill_detected == "y"` readings; `bucket_daily(points, max_abs_daily_l=float(svc detection.max_daily_consumption_cold_l), exclude_days=...)`.
3. `hdd_by_day` from `hdd_data` (all rows, `date.fromisoformat`).
4. `calibrate(...)` with `hw_l_per_day` from the schedule; `k` = fit if not None and `> 0`; else last good `k` from the newest `runway_projection` row; else `DEFAULT_K`.
5. Scenarios from `projection.scenarios` (always ensure `"normal"` exists as `{}`); for each: `simulate(RunwayInputs(today, start_litres, k, hw_by_weekday, climatology(hdd_by_day), parse_multipliers(m), reserve_l, 365))`; `order_by_date(...)` with lead settings. For `normal` only: if `order_by` is not None, simulate again from `order_by` with `level_on(order_by) + min_order_litres` and set `next_order_by` from that run.
6. Return the bundle. `persist_projection` writes one row per scenario with `run_at` = `local_now_str()` style and `series_json = json.dumps(weekly_points(series))`, dates as ISO strings.

`consumption.compute` changes:
- `daily_hw_l` = `hw_litres_per_day_avg(*await load_hw(svc))` (replacing `_hot_water_baseline_l_per_day`; delete the `HW_*` constants and that function).
- Heating: compute `bundle = await project(sf, svc, now=latest_dt)` inside a `try` (log and continue on error). If bundle: `heating_l = bundle.k * today_hdd` (0 if `today_hdd == 0`), `heating_estimate_basis = "model"`; and the runway keys from `bundle.outcomes["normal"]`: `estimated_days_remaining = (run_out - latest_dt.date()).days` (if run_out None: `float(DAYS_REMAINING_CAP_NO_HDD)`), `estimated_empty_date = f"{run_out.isoformat()} 00:00:00"` or None, and the two `remaining_*_hdd` keys mirror them. If no bundle: keep the existing legacy computations (heating blend + flat rate) and `heating_estimate_basis = "legacy"`.
- Add `"heating_estimate_basis"` to the payload (persisted via the T3 column).
- Update the module docstring items 1, 4 and 6.

- [ ] **Step 1: failing tests** in `test_projection_service.py`, seeding `sf` + `seeded_settings`:
  - Seed 90 days of trusted readings falling 1 L/day from 600 in summer (all `hdd_data` 0) with a latest reading of 403: `project` returns `k_source == "default"` (too few heating days), normal `run_out` = today + ceil((403-100)/hw) days where hw = 1.83 (defaults), and `next_order_by` is not None.
  - With `hdd_data` for a synthetic winter (2 years, 10 HDD/day Nov to Feb) and readings consistent with `k=0.17`: `k_source == "fit"` and `k ≈ 0.17 ± 0.03`; `mild_then_cold` order_by ≤ normal order_by + 7 days and `cold` order_by < normal order_by.
  - No readings → `project` returns None.
  - `persist_projection` writes 3 rows; a later `project` with no heating days returns `k_source == "last_good"` and that k.
- [ ] In `test_consumption_analysis.py`: assert `heating_estimate_basis == "model"`, `estimated_daily_heating_consumption_l == 0` when today's HDD is 0, and `estimated_empty_date` comes from the projection (not the old `latest / 1.83`). Update existing assertions that pinned the old flat rate.
- [ ] **Step 3:** implement. **Step 4:** full suite green.

---

## Wave 3

### Task 12: Quote store, price service, yournrg retired (Part B storage)  [model: sonnet]

**Files:**
- Create: `backend/kerotrack/models/price_quote.py`, `backend/kerotrack/quotes/store.py`
- Modify: `backend/kerotrack/db_migrate.py` (import model), `backend/kerotrack/prices/scraper.py`, `backend/kerotrack/prices/service.py`, `backend/kerotrack/prices/cache.py` (only if yournrg keys are referenced), `backend/kerotrack/settings/schema.py` (remove `prices.yournrg_url`), `backend/kerotrack/settings/seeds.py` (`RETIRED_KEYS` += `prices.yournrg_url`), `backend/kerotrack/settings/url_guard.py` (drop yournrg allowlist/validator), `backend/kerotrack/main.py` (wire `quote_lookup`), affected tests (`test_price_scraper.py`, `test_price_service.py`, `test_settings_schema.py`, security invariants yournrg cases)
- Test: `backend/tests/unit/test_quote_store.py`

**Interfaces:**
- Consumes: `quotes.models` (T8).
- Produces:

```python
# models/price_quote.py (table "price_quotes"), columns exactly per spec Part B Storage:
# id, fetched_at, supplier, kind, litres, delivery_by, delivery_label, urgent, ppl_net,
# total_inc_vat, fees_inc_vat, ppl_effective, ok, error

# quotes/store.py
async def save_poll(sf, fetched_at: str, litres: int, results: list[PollResult]) -> int
async def save_index(sf, fetched_at: str, ppl: float | None, source: str) -> None   # kind="index"; ok=0 if ppl None
async def latest_poll(sf) -> list[PriceQuote]        # all rows (kind="quote") sharing the newest fetched_at
async def best_recent(sf, *, now: datetime, max_age_h: int = 36) -> PriceQuote | None  # cheapest ok, non urgent, kind quote, within age
async def history(sf, *, since: datetime) -> list[PriceQuote]   # ordered by fetched_at
```

`save_poll` writes one row per option (`ok=1`, `ppl_effective=effective_ppl(...)`) and, for a result with no options, one `ok=0` row with `error`. `PriceService.__init__` gains `quote_lookup: Callable[[], Awaitable[float | None]] | None = None`; `current_ppl()` returns `await quote_lookup()` when it gives a number, else the scraped BoilerJuice value. In `main.py` build `quote_lookup` as a closure: `best_recent(sf, now=local_now())` → `row.ppl_effective` or None. Remove all yournrg code paths; `fetch_current_price` takes only BoilerJuice; keep the cache file keys it writes for BoilerJuice.

- [ ] **Step 1: failing tests** for `save_poll`/`best_recent` (urgent excluded, stale excluded, ok=0 rows excluded, cheapest wins) and for `PriceService.current_ppl` preferring `quote_lookup` and falling back when it returns None (respx for BoilerJuice).
- [ ] **Step 3:** implement. **Step 4:** full suite green (update/remove yournrg tests; keep BoilerJuice coverage).

## Wave 4

### Task 13: Buying job, MQTT topic, alerts (Part D wiring)  [model: opus]

**Files:**
- Create: `backend/kerotrack/models/buying_state.py`, `backend/kerotrack/buying/service.py`
- Modify: `backend/kerotrack/db_migrate.py`, `backend/kerotrack/publish/mqtt_publisher.py` (`publish_buying`, topic from `mqtt.topic_buying`; find where the publisher is constructed and pass the topic like the others), `backend/kerotrack/scheduler/service.py` (`"buying": "schedule.buying_cron"`), `backend/kerotrack/scheduler/jobs.py` (`JOB_NAMES` += `"buying"`, branch calling `run_buying`)
- Test: `backend/tests/unit/test_buying_service.py`, `backend/tests/unit/test_mqtt_publisher.py` (add buying)

**Interfaces:**
- Consumes: T8 registry/models, T9 signal, T11 `project`/`persist_projection`, T12 store, T2 `notifier.send.send`, `PriceService.refresh()` (`.boilerjuice_ppl`).
- Produces:

```python
# models/buying_state.py (table "buying_state", single row id=1)
class BuyingState(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str]
    last_alerted_state: Mapped[str | None]
    updated_at: Mapped[str]
    summary_json: Mapped[str]

# buying/service.py
async def run_buying(*, sf, settings_service, publisher, prices=None, http_client=None,
                     now: datetime | None = None, apprise_factory=None) -> dict
async def build_summary(sf, svc, *, now: datetime) -> dict   # used by the API; reads persisted rows only
```

`run_buying` steps (each step wrapped so one failure doesn't stop the rest; log exceptions):
1. `aggregate_daily_hdd(sf)`.
2. If `buying.postcode` non empty: `poll(client, QuoteRequest(postcode, order_litres, tanker), providers)` and `save_poll`. Never log the postcode.
3. If `prices` given: `r = await prices.refresh()`; `save_index(sf, now_str, r.boilerjuice_ppl, "boilerjuice")`.
4. `bundle = await project(sf, svc, now=now)`; `persist_projection` if not None.
5. Signal: latest trusted litres → `headroom = capacity * safe_fill_pct - litres`; `best = await best_recent(...)`; `order_by` from active scenario (fall back to normal); `has_index` = an ok index row within 36 h; `state = compute_state(...)`.
6. Load/create `BuyingState`; if `should_alert(row.last_alerted_state if row.state in ALERT_STATES else row.state, state)`. Simplify: alert when `should_alert(row.state if row else None, state)`; on alert set `last_alerted_state = state`. Send via `send(urls, title, body)` with title `f"KeroTrack: {label}"` (`buy_now` → "Buy now", `deadline` → "Order soon", `overdue` → "Order overdue") and a markdown body with best supplier, total, effective ppl, order by date, headroom.
7. Payload for MQTT (exact keys): `state, best_total, best_supplier, best_ppl_effective, trigger_ppl, headroom_l, order_by, run_out, scenario, fetched_at`; `await publisher.publish_buying(payload)`.
8. Return `await build_summary(...)`.

`build_summary` returns: `{"state", "updated_at", "trigger_ppl", "headroom_l", "best": {supplier,total_inc_vat,ppl_effective,delivery_label,fetched_at} | None, "quotes": [latest poll rows as dicts], "scenarios": {name: {run_out, order_by, next_order_by, series}}, "active_scenario", "k", "hw_l_per_day", "context": {"index_percentile_365d", "best_change_30d", "spread_today"}}` from persisted tables only. Percentile: share of `readings.current_ppl > 0` values over the last 365 days that are ≤ the latest index ppl, as 0..100 rounded to 0 dp; None without data.

- [ ] **Step 1: failing tests**:
  - respx HFD fixture + `seeded_settings` with `buying.postcode="ZZ99 9ZZ"`, `buying.trigger_ppl=120`: `run_buying` with a fake publisher (records payloads) and fake apprise factory: price_quotes rows written, state `buy_now`, one alert sent, MQTT payload keys exact.
  - Second run with the same data: state still `buy_now`, **no second alert** (restart safety: create a fresh service call; state comes from the DB).
  - Empty postcode: no HTTP call made (respx asserts no route called), state is `wait` or `unknown`, no exception.
  - The scheduler job map includes `buying` and `run_job("buying", ...)` dispatches.
- [ ] **Step 3:** implement. **Step 4:** full suite green.

## Wave 5

### Task 14: Buying API (Part D endpoints)  [model: sonnet]

**Files:** Create `backend/kerotrack/api/routes/buying.py`; Modify `backend/kerotrack/main.py` (include router); Test `backend/tests/api/test_buying_routes.py`

**Interfaces:** Produces `GET /api/buying/summary` → `build_summary`; `GET /api/buying/quotes?days=90` (1..730) → `{"items": [...]}` from `history`; `POST /api/buying/run` → `await request.app.state.scheduler.trigger_now("buying")` returning the summary; `POST /api/buying/calibrate` → `run_calibration` result as dict plus `current_burner_minutes`, `current_hw_l_per_day`. Follow `api/routes/analysis.py` style. Read an existing API test (e.g. `tests/api/test_*`) for the authenticated client + CSRF fixture pattern.

- [ ] **Step 1: failing tests:** unauthenticated GET → 401; authenticated summary → 200 with `state` key (seed a `BuyingState`); POST without CSRF → 403; POST calibrate with CSRF → 200 with `k` key. Security invariants suite still passes.
- [ ] **Step 3/4:** implement, full suite green.

## Wave 6

### Task 15: Frontend Buying page + badge  [model: sonnet]

**Files:**
- Create: `frontend/src/routes/buying/+page.svelte`, `frontend/src/lib/components/BuyingBadge.svelte`, test `frontend/src/lib/buying.test.ts` (pure formatting helpers in `frontend/src/lib/buying.ts`)
- Modify: `frontend/src/lib/api.ts` (add `getBuyingSummary`, `getBuyingQuotes`, `runBuying`, `calibrateBuying` following existing patterns incl. CSRF header), `frontend/src/lib/types/api.ts` (types for the summary), `frontend/src/lib/components/Sidebar.svelte` (Buying link), `frontend/src/routes/+page.svelte` (badge)

Page sections per spec Part E using existing `LineChart.svelte` (read its props first). States map to colours: `buy_now` green, `deadline` amber, `overdue` red, `no_room`/`wait`/`unknown` neutral. Helpers in `buying.ts`: `stateLabel(state)`, `stateTone(state)`, `formatPpl(n)` (`"110.0p"`), `formatGBP(n)` (`"£577.71"`), `daysUntil(iso, today)`. vitest covers the helpers. Run `npm run check` and `npm test` in `frontend/`.

- [ ] Steps: failing vitest for helpers → implement → page + badge → `npm run check`, `npm test`, `npm run build` all pass.
- [ ] Browser verification against a **local instance with synthetic data** (repo ritual step 4): run backend with a temp DB seeded via the API, open `/buying`, screenshot, check console.

---

## Final review, rehearsal, deploy

- [ ] **Whole branch review** [opus]: spec coverage, security invariants, no doxing (grep for the real postcode area and email domain must return nothing), no RFC 1918 literals.
- [ ] **Local rehearsal on a copy of prod data:** copy the snapshot DB to a temp data dir, start the backend locally against it (env: data dir + a throwaway `APP_SECRET_KEY`), let startup migrate (settings rewrite, columns), run jobs `analysis`, `cost_analysis`, `buying` through the admin route, sanity check: notifier cron now `0 8 * * *`, `refill_periods` rebuilt on manual refills, `estimated_empty_date` in early 2027 not May, `k` 0.1 to 0.25, HFD quote stored (the postcode is entered in the local settings only, never committed).
- [ ] **Push + CI:** push `feat/buy-planner`, fast forward `main`, push; wait for `Build container images` green.
- [ ] **Deploy (with rollback):** record current image digests (`docker --context docker-host inspect kerotrack-api --format '{{.Image}}'`, same for ui) and tag them `kerotrack-api:rollback-20261004` on the host; `docker stop kerotrack-api`; `cp -a /dockerdata/kerotrack/data /dockerdata/backups/kerotrack-<ts>`; `docker --context docker-host compose up -d` from the repo (with `compose.override.yaml` present); verify `/api/health`, logs now show INFO lines, run the `buying` job, check `oiltank/buying` retained message. Set `buying.postcode` on prod through the settings API (value never written to the repo or logs).
- [ ] **Rollback recipe** (if needed): stop containers, restore the backup dir over `/dockerdata/kerotrack/data`, retag rollback images as `latest` (or run with `KEROTRACK_TAG=sha-<old>`), `compose up -d`.
