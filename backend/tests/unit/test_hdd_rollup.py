"""Daily HDD roll-up (KERO-H1) — per-reading HDD values → daily hdd_data rows."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.consumption import compute, run_analysis
from kerotrack.analysis.hdd_rollup import aggregate_daily_hdd
from kerotrack.models.hdd import HddDatum
from kerotrack.models.reading import Reading
from kerotrack.publish.mqtt_publisher import MqttPublisher

pytestmark = pytest.mark.asyncio


def _reading(date: str, hdd: float | None, litres: float = 1000.0) -> Reading:
    return Reading(
        date=date,
        id="probe",
        temperature=12.0,
        litres_remaining=litres,
        air_gap_cm=40.0,
        heating_degree_days=hdd,
        refill_detected="n",
        leak_detected="n",
    )


async def _all_hdd(sf: async_sessionmaker) -> dict[str, float | None]:
    async with sf() as session:
        rows = (await session.execute(select(HddDatum))).scalars().all()
    return {r.date: r.hdd for r in rows}


async def test_aggregates_mean_per_day(sf: async_sessionmaker) -> None:
    async with sf() as session:
        session.add(_reading("2026-01-05 06:00:00", 10.0))
        session.add(_reading("2026-01-05 18:00:00", 6.0))
        session.add(_reading("2026-01-06 12:00:00", 3.5))
        await session.commit()

    written = await aggregate_daily_hdd(sf)

    assert written == 2
    assert await _all_hdd(sf) == {"2026-01-05": 8.0, "2026-01-06": 3.5}


async def test_skips_readings_without_hdd(sf: async_sessionmaker) -> None:
    async with sf() as session:
        session.add(_reading("2026-01-05 06:00:00", None))
        await session.commit()

    assert await aggregate_daily_hdd(sf) == 0
    assert await _all_hdd(sf) == {}


async def test_upserts_existing_rows(sf: async_sessionmaker) -> None:
    """Re-running after new readings updates the day's row in place —
    including overwriting a migrated monthly row on a first-of-month key."""
    async with sf() as session:
        session.add(HddDatum(date="2026-01-01", hdd=250.0))  # v1 monthly lump
        session.add(_reading("2026-01-01 06:00:00", 12.0))
        await session.commit()

    assert await aggregate_daily_hdd(sf) == 1
    assert await _all_hdd(sf) == {"2026-01-01": 12.0}

    # Idempotent when nothing changed.
    assert await aggregate_daily_hdd(sf) == 0

    # New reading on the same day shifts the mean.
    async with sf() as session:
        session.add(_reading("2026-01-01 18:00:00", 6.0))
        await session.commit()
    assert await aggregate_daily_hdd(sf) == 1
    assert await _all_hdd(sf) == {"2026-01-01": 9.0}


async def test_run_analysis_populates_hdd_data(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """The scheduled analysis run writes hdd_data (Verify: count grows)."""
    async with sf() as session:
        for i in range(10):
            session.add(
                _reading(
                    f"2026-01-{5 + i:02d} 12:00:00",
                    hdd=8.0 + i * 0.1,
                    litres=1000.0 - i * 8.0,
                )
            )
        await session.commit()

    class Recorder:
        async def publish(self, topic, body, *, qos=0, retain=False):
            pass

    payload = await run_analysis(
        sf=sf, settings_service=seeded_settings, publisher=MqttPublisher(client=Recorder())
    )
    assert payload is not None
    assert len(await _all_hdd(sf)) == 10


async def test_heating_consumption_nonzero_on_cold_days(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """With daily hdd_data present, today_hdd > 0 so heating_l is no longer
    forced to zero (the KERO-H1 failure mode)."""
    async with sf() as session:
        for i in range(10):
            session.add(
                _reading(
                    f"2026-01-{5 + i:02d} 12:00:00",
                    hdd=9.0,
                    litres=1000.0 - i * 10.0,
                )
            )
        await session.commit()

    await aggregate_daily_hdd(sf)
    payload = await compute(sf, seeded_settings)

    assert payload is not None
    assert payload["estimated_daily_heating_consumption_l"] > 0
    assert payload["consumption_per_hdd_l"] > 0
