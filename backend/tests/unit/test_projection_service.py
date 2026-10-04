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
