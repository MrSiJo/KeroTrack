"""Runway projection service (spec A4, Part C).

Loads trusted readings and degree days, calibrates litres per HDD (``k``),
then runs the seasonal runway simulation for every configured scenario and
derives the run out and order by dates. With at least 12 months of Nest
heating hours and a positive Nest fit, the heating term is litres per
heating hour times the expected heating hours instead (``heating_model``
"nest"); ``k`` is still fitted and persisted as the HDD fallback. ``persist_projection`` stores one
``runway_projection`` row per scenario; the newest stored ``k`` is the
fallback when a later fit fails.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.daily_usage import Calibration, Point, bucket_daily, calibrate
from kerotrack.analysis.nest_model import (
    calibrate_nest,
    expected_hours_fn,
    monthly_usage,
    nest_model_active,
)
from kerotrack.analysis.hot_water import (
    hw_litres_for_weekday,
    hw_litres_per_day_avg,
    slots_per_week,
    validate_schedule,
)
from kerotrack.clock import local_now, parse_local
from kerotrack.ingest.nest import load_nest_monthly
from kerotrack.models.hdd import HddDatum
from kerotrack.models.reading import Reading, trusted_readings_clause
from kerotrack.models.refill import ActualRefillCost
from kerotrack.models.runway_projection import RunwayProjection
from kerotrack.projection.runway import (
    RunwayInputs,
    climatology,
    order_by_date,
    parse_multipliers,
    simulate,
    weekly_points,
)
from kerotrack.settings.schema import get_setting_def
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)

DEFAULT_K = 0.16
CALIBRATION_WINDOW_DAYS = 400
# The Nest fit is monthly, so it looks further back for clean months.
NEST_CALIBRATION_WINDOW_DAYS = 730
HORIZON_DAYS = 365
NORMAL = "normal"
_TS_FMT = "%Y-%m-%d %H:%M:%S"
# Ceiling on a believable daily HDD value. A day derived from tank temperature
# against base 15.5 C cannot exceed about 35, so anything above this is one of
# the v1 migration's MONTHLY totals keyed on the 1st of the month (readings had
# a gap, so the daily roll-up never overwrote them). Those rows are excluded
# from climatology and calibration rather than read as a single freezing day.
MAX_DAILY_HDD = 40.0


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    scenario: str
    run_out: date | None
    order_by: date | None
    next_order_by: date | None  # normal only, else None
    series: list[tuple[date, float]]


@dataclass(frozen=True, slots=True)
class ProjectionBundle:
    run_at: datetime
    start_litres: float
    k: float
    k_source: str  # "fit" | "last_good" | "default"
    hw_l_per_day: float
    hw_by_weekday: dict[int, float]
    calibration: Calibration
    outcomes: dict[str, ScenarioOutcome]
    active_scenario: str
    heating_model: str = "hdd"  # "nest" | "hdd"
    l_per_heating_hour: float | None = None  # set under the Nest model only
    # Expected heating hours on a day (Nest model only).
    expected_heating_hours: Callable[[date], float] | None = None


async def load_hw(svc: SettingsService) -> tuple[list[dict], float, float]:
    """Return ``(schedule, burner_minutes_per_slot, fuel_rate_l_per_h)``.

    A stored schedule that fails validation falls back to the shipped default
    so a bad edit can't take the analysis down.
    """
    raw = await svc.get("boiler.hw_schedule")
    try:
        schedule = validate_schedule(raw)
    except ValueError:
        logger.warning("boiler.hw_schedule is invalid; using the default schedule")
        schedule = validate_schedule(get_setting_def("boiler.hw_schedule").default)
    minutes = float(await svc.get("boiler.hw_burner_minutes_per_slot"))
    rate = float(await svc.get("boiler.fuel_rate_l_per_h"))
    return schedule, minutes, rate


def _day_of(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


async def _trusted_readings_since(sf: async_sessionmaker, start: datetime) -> list[Reading]:
    async with sf() as session:
        return list(
            (
                await session.execute(
                    select(Reading)
                    .where(Reading.date >= start.strftime(_TS_FMT), trusted_readings_clause())
                    .order_by(Reading.date)
                )
            )
            .scalars()
            .all()
        )


async def _manual_refill_days(sf: async_sessionmaker) -> set[date]:
    async with sf() as session:
        values = (await session.execute(select(ActualRefillCost.refill_date))).scalars().all()
    out: set[date] = set()
    for v in values:
        d = _day_of(v)
        if d is not None:
            out |= {d - timedelta(days=1), d, d + timedelta(days=1)}
    return out


async def _hdd_by_day(sf: async_sessionmaker) -> dict[date, float]:
    """Daily HDD by local day, skipping v1 monthly totals (> ``MAX_DAILY_HDD``).

    Feeds both calibration and climatology, so the filter covers both.
    """
    async with sf() as session:
        rows = (await session.execute(select(HddDatum))).scalars().all()
    out: dict[date, float] = {}
    for r in rows:
        d = _day_of(r.date)
        if d is None:
            continue
        value = float(r.hdd or 0.0)
        if value > MAX_DAILY_HDD:
            continue
        out[d] = value
    return out


async def _last_good_k(sf: async_sessionmaker) -> float | None:
    async with sf() as session:
        return (
            await session.execute(
                select(RunwayProjection.k)
                .where(RunwayProjection.k > 0)
                .order_by(desc(RunwayProjection.id))
                .limit(1)
            )
        ).scalar_one_or_none()


async def _calibrate_with(
    sf: async_sessionmaker,
    svc: SettingsService,
    *,
    now: datetime,
    hdd_by_day: dict[date, float],
    schedule: list[dict],
    minutes: float,
    rate: float,
    nest_monthly: dict[str, float] | None = None,
) -> Calibration:
    readings = await _trusted_readings_since(
        sf, now - timedelta(days=max(CALIBRATION_WINDOW_DAYS, NEST_CALIBRATION_WINDOW_DAYS))
    )
    points: list[Point] = []
    exclude = await _manual_refill_days(sf)
    for r in readings:
        when = parse_local(r.date)
        if when is None:
            continue
        if r.refill_detected == "y":
            exclude.add(when.date())
        if r.litres_remaining is None:
            continue
        points.append(Point(when, float(r.litres_remaining)))
    days = bucket_daily(
        points,
        max_abs_daily_l=float(await svc.get("detection.max_daily_consumption_cold_l")),
        exclude_days=exclude,
    )
    slots = slots_per_week(schedule)
    hw_sched = hw_litres_per_day_avg(schedule, minutes, rate)
    # The HDD fit keeps its 400 day window (the first day of a window has no
    # previous day, so it starts the day after).
    hdd_start = (now - timedelta(days=CALIBRATION_WINDOW_DAYS)).date()
    nest_start = (now - timedelta(days=NEST_CALIBRATION_WINDOW_DAYS)).date()
    cal = calibrate(
        [d for d in days if d.day > hdd_start],
        hdd_by_day,
        hw_l_per_day=hw_sched,
        slots_per_week=slots,
        fuel_rate_l_per_h=rate,
    )
    if nest_monthly is None:
        nest_monthly = await load_nest_monthly(sf)
    nest = calibrate_nest(
        monthly_usage([d for d in days if d.day > nest_start]),
        nest_monthly,
        hw_fixed=hw_sched,
    )
    active = nest_model_active(nest_monthly, nest.a)
    cal = replace(
        cal,
        heating_model="nest" if active else "hdd",
        l_per_heating_hour=nest.a,
        nest_months_used=nest.months_used,
        hw_per_day_nest=nest.hw_per_day,
        l_per_heating_hour_free=nest.a_free,
        nest_months_excluded=nest.months_excluded,
    )
    if active:
        hw = nest.hw_per_day
        minutes_prop = (
            hw * 7 * 60 / (slots * rate)
            if hw is not None and hw > 0 and slots > 0 and rate > 0
            else None
        )
        cal = replace(cal, proposed_burner_minutes=minutes_prop)
    return cal


async def run_calibration(
    sf: async_sessionmaker, svc: SettingsService, *, now: datetime
) -> Calibration:
    """Fit ``k`` (400 days), the Nest model (730 days) and the hot water proposal."""
    schedule, minutes, rate = await load_hw(svc)
    return await _calibrate_with(
        sf,
        svc,
        now=now,
        hdd_by_day=await _hdd_by_day(sf),
        schedule=schedule,
        minutes=minutes,
        rate=rate,
    )


async def _scenarios(svc: SettingsService) -> dict[str, dict]:
    raw = await svc.get("projection.scenarios")
    if not isinstance(raw, dict):
        logger.warning("projection.scenarios is not an object; projecting normal only")
        return {NORMAL: {}}
    out: dict[str, dict] = {
        str(name): (mult if isinstance(mult, dict) else {}) for name, mult in raw.items()
    }
    out.setdefault(NORMAL, {})
    return out


async def project(
    sf: async_sessionmaker, svc: SettingsService, *, now: datetime | None = None
) -> ProjectionBundle | None:
    """Run every scenario from the latest trusted level. None without a reading."""
    now = now or local_now()
    today = now.date()

    async with sf() as session:
        latest = (
            await session.execute(
                select(Reading)
                .where(trusted_readings_clause(), Reading.litres_remaining.is_not(None))
                .order_by(desc(Reading.date))
                .limit(1)
            )
        ).scalar_one_or_none()
    if latest is None:
        return None
    start_litres = float(latest.litres_remaining or 0.0)

    schedule, minutes, rate = await load_hw(svc)
    hw_l_per_day = hw_litres_per_day_avg(schedule, minutes, rate)
    hw_by_weekday = {wd: hw_litres_for_weekday(schedule, wd, minutes, rate) for wd in range(7)}
    hdd_by_day = await _hdd_by_day(sf)
    nest_monthly = await load_nest_monthly(sf)

    calibration = await _calibrate_with(
        sf,
        svc,
        now=now,
        hdd_by_day=hdd_by_day,
        schedule=schedule,
        minutes=minutes,
        rate=rate,
        nest_monthly=nest_monthly,
    )
    if calibration.k is not None and calibration.k > 0:
        k, k_source = calibration.k, "fit"
    else:
        last = await _last_good_k(sf)
        if last is not None:
            k, k_source = float(last), "last_good"
        else:
            k, k_source = DEFAULT_K, "default"

    reserve_l = float(await svc.get("projection.reserve_l"))
    lead_days = int(await svc.get("buying.lead_time_days"))
    winter_extra = int(await svc.get("buying.winter_lead_extra_days"))
    min_order = float(await svc.get("buying.min_order_litres"))
    fill_cap = float(await svc.get("tank.capacity_l")) * float(
        await svc.get("buying.safe_fill_pct")
    )
    expected_hdd = climatology(hdd_by_day)

    heating_model = calibration.heating_model
    a: float | None = None
    expected_hours: Callable[[date], float] | None = None
    heating_l: Callable[[date], float] | None = None
    if heating_model == "nest" and calibration.l_per_heating_hour is not None:
        a = float(calibration.l_per_heating_hour)
        expected_hours = expected_hours_fn(nest_monthly)
        nest_a, nest_hours = a, expected_hours

        def heating_l(d: date) -> float:
            return nest_a * nest_hours(d)
    else:
        heating_model = "hdd"

    def run(start_day: date, litres: float, multipliers: dict[int, float]):
        return simulate(
            RunwayInputs(
                start_day=start_day,
                start_litres=litres,
                k=k,
                hw_by_weekday=hw_by_weekday,
                expected_hdd=expected_hdd,
                multipliers=multipliers,
                reserve_l=reserve_l,
                horizon_days=HORIZON_DAYS,
                heating_l=heating_l,
            )
        )

    outcomes: dict[str, ScenarioOutcome] = {}
    for name, raw_mult in (await _scenarios(svc)).items():
        multipliers = parse_multipliers(raw_mult)
        result = run(today, start_litres, multipliers)
        order_by = order_by_date(
            result.run_out, lead_days=lead_days, winter_extra_days=winter_extra
        )
        next_order_by: date | None = None
        if name == NORMAL and order_by is not None:
            levels = dict(result.series)
            # order_by can sit before today when the tank is already low.
            level_then = levels.get(order_by, start_litres)
            # An order can't fill past the safe fill level.
            after_litres = min(level_then + min_order, fill_cap)
            after = run(max(order_by, today), after_litres, multipliers)
            next_order_by = order_by_date(
                after.run_out, lead_days=lead_days, winter_extra_days=winter_extra
            )
        outcomes[name] = ScenarioOutcome(
            scenario=name,
            run_out=result.run_out,
            order_by=order_by,
            next_order_by=next_order_by,
            series=result.series,
        )

    active = str(await svc.get("projection.active_scenario") or NORMAL)
    if active not in outcomes:
        logger.warning("projection.active_scenario %r is not defined; using normal", active)
        active = NORMAL

    return ProjectionBundle(
        run_at=now,
        start_litres=start_litres,
        k=k,
        k_source=k_source,
        hw_l_per_day=hw_l_per_day,
        hw_by_weekday=hw_by_weekday,
        calibration=calibration,
        outcomes=outcomes,
        active_scenario=active,
        heating_model=heating_model,
        l_per_heating_hour=a,
        expected_heating_hours=expected_hours,
    )


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


async def persist_projection(sf: async_sessionmaker, bundle: ProjectionBundle) -> None:
    """Write one ``runway_projection`` row per scenario."""
    run_at = bundle.run_at.strftime(_TS_FMT)
    async with sf() as session:
        for outcome in bundle.outcomes.values():
            session.add(
                RunwayProjection(
                    run_at=run_at,
                    scenario=outcome.scenario,
                    k=bundle.k,
                    hw_l_per_day=bundle.hw_l_per_day,
                    start_litres=bundle.start_litres,
                    run_out_date=_iso(outcome.run_out),
                    order_by_date=_iso(outcome.order_by),
                    next_order_by_date=_iso(outcome.next_order_by),
                    series_json=json.dumps(weekly_points(outcome.series)),
                )
            )
        await session.commit()
