"""Projection service: calibration wiring, scenarios, persistence (spec A4, Part C)."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.hot_water import hw_litres_for_weekday
from kerotrack.models.hdd import HddDatum
from kerotrack.models.reading import Reading
from kerotrack.models.runway_projection import RunwayProjection
from kerotrack.projection.service import (
    DEFAULT_K,
    MAX_DAILY_HDD,
    _hdd_by_day,
    load_hw,
    persist_projection,
    project,
)

pytestmark = pytest.mark.asyncio

TRUE_K = 0.17


def _reading(when: datetime, litres: float, refill: str = "n") -> Reading:
    return Reading(
        date=when.strftime("%Y-%m-%d %H:%M:%S"),
        id="probe",
        litres_remaining=litres,
        refill_detected=refill,
        leak_detected="n",
    )


async def _seed_summer(sf: async_sessionmaker, now: datetime) -> None:
    """90 days falling 1 L/day from 600, then a latest reading of 403; HDD 0."""
    first = now.date() - timedelta(days=90)
    async with sf() as session:
        for i in range(90):
            d = first + timedelta(days=i)
            session.add(_reading(datetime(d.year, d.month, d.day, 12), 600.0 - i))
            session.add(HddDatum(date=d.isoformat(), hdd=0.0))
        session.add(_reading(now.replace(hour=12, minute=0), 403.0))
        session.add(HddDatum(date=now.date().isoformat(), hdd=0.0))
        await session.commit()


def _winter_hdd(d: date) -> float:
    return 10.0 if d.month in (11, 12, 1, 2) else 0.0


async def _seed_winter(sf: async_sessionmaker, svc, now: datetime) -> None:
    """Two years of synthetic HDD and 400 days of readings with k = 0.17."""
    schedule, minutes, rate = await load_hw(svc)
    hw = {wd: hw_litres_for_weekday(schedule, wd, minutes, rate) for wd in range(7)}
    today = now.date()
    async with sf() as session:
        for i in range(730):
            d = today - timedelta(days=i)
            session.add(HddDatum(date=d.isoformat(), hdd=_winter_hdd(d)))
        days = [today - timedelta(days=399 - i) for i in range(400)]
        draws = [hw[d.weekday()] + TRUE_K * _winter_hdd(d) for d in days[1:]]
        level = 600.0 + sum(draws)  # latest lands at 600 L
        session.add(_reading(datetime(days[0].year, days[0].month, days[0].day, 12), level))
        for d, draw in zip(days[1:], draws):
            level -= draw
            session.add(_reading(datetime(d.year, d.month, d.day, 12), level))
        await session.commit()


async def test_summer_only_uses_default_k_and_flat_hot_water(
    sf: async_sessionmaker, seeded_settings
) -> None:
    now = datetime(2026, 8, 31, 18, 0)
    await _seed_summer(sf, now)

    bundle = await project(sf, seeded_settings, now=now)

    assert bundle is not None
    assert bundle.k_source == "default"
    assert bundle.k == DEFAULT_K
    assert bundle.start_litres == pytest.approx(403.0)
    assert bundle.hw_l_per_day == pytest.approx(1.83, abs=0.01)
    assert bundle.active_scenario == "normal"
    assert set(bundle.outcomes) == {"normal", "mild_then_cold", "cold"}
    normal = bundle.outcomes["normal"]
    expected = now.date() + timedelta(days=math.ceil((403 - 100) / 1.83))
    assert normal.run_out is not None
    # Per weekday hot water varies (1 or 2 slots), so allow a day either way.
    assert abs((normal.run_out - expected).days) <= 1
    assert normal.order_by is not None
    assert normal.next_order_by is not None
    assert normal.next_order_by > normal.order_by
    # No heating anywhere, so every scenario runs out the same day.
    assert bundle.outcomes["cold"].run_out == normal.run_out
    assert bundle.outcomes["cold"].next_order_by is None
    assert normal.series[0] == (now.date(), pytest.approx(403.0))


async def test_winter_history_fits_k_and_orders_scenarios(
    sf: async_sessionmaker, seeded_settings
) -> None:
    now = datetime(2026, 10, 4, 18, 0)
    await _seed_winter(sf, seeded_settings, now)

    bundle = await project(sf, seeded_settings, now=now)

    assert bundle is not None
    assert bundle.k_source == "fit"
    assert bundle.k == pytest.approx(TRUE_K, abs=0.03)
    assert bundle.calibration.heating_days >= 30
    normal = bundle.outcomes["normal"].order_by
    mild = bundle.outcomes["mild_then_cold"].order_by
    cold = bundle.outcomes["cold"].order_by
    assert normal is not None and mild is not None and cold is not None
    assert mild <= normal + timedelta(days=7)
    assert cold < normal


async def test_no_readings_returns_none(sf: async_sessionmaker, seeded_settings) -> None:
    assert await project(sf, seeded_settings, now=datetime(2026, 10, 4, 18, 0)) is None


async def test_persist_then_last_good_k(sf: async_sessionmaker, seeded_settings) -> None:
    now = datetime(2026, 10, 4, 18, 0)
    await _seed_winter(sf, seeded_settings, now)
    bundle = await project(sf, seeded_settings, now=now)
    assert bundle is not None and bundle.k_source == "fit"

    await persist_projection(sf, bundle)

    async with sf() as session:
        rows = (await session.execute(select(RunwayProjection))).scalars().all()
    assert len(rows) == 3
    by_name = {r.scenario: r for r in rows}
    assert set(by_name) == {"normal", "mild_then_cold", "cold"}
    normal = by_name["normal"]
    assert normal.run_at == "2026-10-04 18:00:00"
    assert normal.k == pytest.approx(bundle.k)
    assert normal.start_litres == pytest.approx(600.0, abs=0.5)
    assert normal.run_out_date == bundle.outcomes["normal"].run_out.isoformat()
    assert normal.order_by_date == bundle.outcomes["normal"].order_by.isoformat()
    assert normal.next_order_by_date is not None
    assert by_name["cold"].next_order_by_date is None
    series = json.loads(normal.series_json)
    assert series[0] == ["2026-10-04", pytest.approx(600.0, abs=0.5)]
    date.fromisoformat(series[-1][0])

    # Wipe the heating signal: the fit now fails, so the last good k is used.
    async with sf() as session:
        await session.execute(update(HddDatum).values(hdd=0.0))
        await session.commit()
    later = await project(sf, seeded_settings, now=now)
    assert later is not None
    assert later.k_source == "last_good"
    assert later.k == pytest.approx(bundle.k)


async def test_malformed_scenarios_fall_back_to_normal(
    sf: async_sessionmaker, seeded_settings
) -> None:
    now = datetime(2026, 8, 31, 18, 0)
    await _seed_summer(sf, now)
    await seeded_settings.set("projection.scenarios", ["not", "a", "dict"])

    bundle = await project(sf, seeded_settings, now=now)

    assert bundle is not None
    assert set(bundle.outcomes) == {"normal"}


async def test_v1_monthly_hdd_lumps_are_ignored(sf: async_sessionmaker, seeded_settings) -> None:
    """A v1 monthly total keyed on the 1st (e.g. 322) is not a daily value."""
    now = datetime(2026, 8, 31, 18, 0)
    await _seed_summer(sf, now)
    baseline = await project(sf, seeded_settings, now=now)
    assert baseline is not None

    async with sf() as session:
        session.add(HddDatum(date="2024-01-01", hdd=322.0))
        session.add(HddDatum(date="2024-01-02", hdd=12.5))
        await session.commit()

    by_day = await _hdd_by_day(sf)
    assert date(2024, 1, 1) not in by_day
    assert by_day[date(2024, 1, 2)] == pytest.approx(12.5)
    assert all(v <= MAX_DAILY_HDD for v in by_day.values())

    # Drop the normal January row too: with only the lump left, January's
    # climatology must stay at zero, so the run out date does not move.
    async with sf() as session:
        row = (
            await session.execute(select(HddDatum).where(HddDatum.date == "2024-01-02"))
        ).scalar_one()
        await session.delete(row)
        await session.commit()
    bundle = await project(sf, seeded_settings, now=now)
    assert bundle is not None
    assert bundle.outcomes["normal"].run_out == baseline.outcomes["normal"].run_out


async def test_after_order_level_is_capped_at_safe_fill(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """An order can't fill past capacity * safe_fill_pct (600 * 0.95 = 570 L)."""
    now = datetime(2026, 8, 31, 18, 0)
    await _seed_summer(sf, now)
    await seeded_settings.set("tank.capacity_l", 600.0)
    nexts = []
    for min_order in (500, 550):
        await seeded_settings.set("buying.min_order_litres", min_order)
        bundle = await project(sf, seeded_settings, now=now)
        assert bundle is not None
        nexts.append(bundle.outcomes["normal"].next_order_by)
    # Both orders overflow the cap, so both refill to the same level.
    assert nexts[0] is not None and nexts[0] == nexts[1]


# ----- Nest heating hours model (synthetic) --------------------------------

NEST_A = 0.7
NEST_HOURS = {1: 70.0, 2: 50.0, 3: 40.0, 4: 20.0, 5: 4.0, 6: 0.0, 7: 0.0, 8: 0.0,
              9: 0.0, 10: 6.0, 11: 30.0, 12: 45.0}


def _nest_heating(d: date) -> float:
    import calendar

    return NEST_A * NEST_HOURS[d.month] / calendar.monthrange(d.year, d.month)[1]


async def _seed_nest(
    sf: async_sessionmaker, svc, now: datetime, *, months: int, n_days: int = 400
) -> None:
    """``n_days`` of readings drawn as hot water + a * hours/day, plus
    ``months`` of Nest monthly hours ending with the current month."""
    from kerotrack.ingest.nest import import_nest_months

    schedule, minutes, rate = await load_hw(svc)
    hw = {wd: hw_litres_for_weekday(schedule, wd, minutes, rate) for wd in range(7)}
    today = now.date()
    days = [today - timedelta(days=n_days - 1 - i) for i in range(n_days)]
    draws = [hw[d.weekday()] + _nest_heating(d) for d in days[1:]]
    level = 600.0 + sum(draws)
    async with sf() as session:
        session.add(_reading(datetime(days[0].year, days[0].month, days[0].day, 12), level))
        for d, draw in zip(days[1:], draws):
            level -= draw
            session.add(_reading(datetime(d.year, d.month, d.day, 12), level))
        await session.commit()
    rows = []
    y, m = today.year, today.month
    for _ in range(months):
        rows.append((f"{y:04d}-{m:02d}", NEST_HOURS[m], "report"))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    await import_nest_months(sf, rows)


async def test_nest_model_active_with_twelve_months(sf: async_sessionmaker, seeded_settings) -> None:
    now = datetime(2026, 10, 4, 18, 0)
    await _seed_nest(sf, seeded_settings, now, months=24)

    bundle = await project(sf, seeded_settings, now=now)

    assert bundle is not None
    assert bundle.heating_model == "nest"
    assert bundle.l_per_heating_hour == pytest.approx(NEST_A, abs=0.02)
    cal = bundle.calibration
    assert cal.heating_model == "nest"
    assert cal.l_per_heating_hour == pytest.approx(NEST_A, abs=0.02)
    assert cal.hw_per_day_nest == pytest.approx(bundle.hw_l_per_day, abs=0.05)
    assert cal.nest_months_used >= 12
    assert cal.nest_months_excluded == 0
    assert cal.l_per_heating_hour_free == pytest.approx(NEST_A, abs=0.02)
    assert cal.proposed_burner_minutes is not None
    # The heating term is a * expected hours; today is in October.
    expected_hours = bundle.expected_heating_hours(now.date())
    assert expected_hours == pytest.approx(6.0 / 31)
    normal = bundle.outcomes["normal"]
    first_draw = normal.series[0][1] - normal.series[1][1]
    assert first_draw == pytest.approx(
        bundle.hw_by_weekday[now.date().weekday()] + bundle.l_per_heating_hour * 6.0 / 31,
        abs=1e-6,
    )
    # Cold scenario multiplies the Nest heating term, so it orders earlier.
    assert bundle.outcomes["cold"].order_by < normal.order_by
    # The HDD k is still what gets persisted (no HDD here, so the default).
    assert bundle.k == DEFAULT_K


async def test_nest_model_needs_twelve_months(sf: async_sessionmaker, seeded_settings) -> None:
    now = datetime(2026, 10, 4, 18, 0)
    await _seed_nest(sf, seeded_settings, now, months=11)

    bundle = await project(sf, seeded_settings, now=now)

    assert bundle is not None
    assert bundle.heating_model == "hdd"
    assert bundle.l_per_heating_hour is None
    assert bundle.expected_heating_hours is None
    assert bundle.calibration.heating_model == "hdd"
    # Nest months Dec 2025 to Oct 2026 overlap usage months up to Sep 2026.
    assert bundle.calibration.nest_months_used == 10


async def test_no_nest_data_keeps_hdd_model(sf: async_sessionmaker, seeded_settings) -> None:
    now = datetime(2026, 10, 4, 18, 0)
    await _seed_winter(sf, seeded_settings, now)
    bundle = await project(sf, seeded_settings, now=now)
    assert bundle is not None
    assert bundle.heating_model == "hdd"
    assert bundle.calibration.heating_model == "hdd"
    assert bundle.calibration.l_per_heating_hour is None
    assert bundle.calibration.nest_months_used == 0
    assert bundle.calibration.hw_per_day_nest is None


async def test_nest_calibration_uses_730_days(sf: async_sessionmaker, seeded_settings) -> None:
    from kerotrack.projection.service import NEST_CALIBRATION_WINDOW_DAYS

    assert NEST_CALIBRATION_WINDOW_DAYS == 730
    now = datetime(2026, 10, 4, 18, 0)
    await _seed_nest(sf, seeded_settings, now, months=30, n_days=760)
    bundle = await project(sf, seeded_settings, now=now)
    assert bundle is not None
    # About 24 months of usable readings, far beyond the 400 day HDD window.
    assert bundle.calibration.nest_months_used >= 22
    assert bundle.heating_model == "nest"
    assert bundle.l_per_heating_hour == pytest.approx(NEST_A, abs=0.02)
    # The HDD fit still only looks at 400 days.
    assert bundle.calibration.days_used <= 400


async def test_sensor_blind_months_reported(sf: async_sessionmaker, seeded_settings) -> None:
    now = datetime(2026, 10, 4, 18, 0)
    await _seed_nest(sf, seeded_settings, now, months=24)
    # Flatten the readings for June and July 2026: the sensor saw nothing.
    async with sf() as session:
        await session.execute(
            update(Reading)
            .where(Reading.date >= "2026-06-01", Reading.date < "2026-08-01")
            .values(litres_remaining=None)
        )
        await session.commit()
    async with sf() as session:
        rows = (
            await session.execute(
                select(Reading).where(Reading.date >= "2026-05-31", Reading.date < "2026-08-01")
                .order_by(Reading.date)
            )
        ).scalars().all()
        level = rows[0].litres_remaining
        for r in rows[1:]:
            r.litres_remaining = level  # perfectly flat: 0 L/day
        await session.commit()
    bundle = await project(sf, seeded_settings, now=now)
    assert bundle is not None
    assert bundle.calibration.nest_months_excluded == 2
    assert bundle.l_per_heating_hour == pytest.approx(NEST_A, abs=0.02)
