"""Verify downstream walkers skip noise_suppressed rows so the noisy
litres/air_gap values don't pollute consumption + cost calculations.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.consumption import _readings_in_window
from kerotrack.analysis.cost import _readings_between
from kerotrack.models.reading import Reading
from kerotrack.notifier.apprise_notifier import _fetch_readings_between


pytestmark = pytest.mark.asyncio


async def _seed_noise_window(sf: async_sessionmaker) -> None:
    async with sf() as session:
        # Three rows: 12:00 good (520 L), 12:30 noisy (329 L → spike),
        # 13:00 good (520 L). The middle row is what historically
        # polluted "used litres".
        for date, litres, ag, flags in [
            ("2026-05-24 12:00:00", 520.0, 80.0, "144"),
            ("2026-05-24 12:30:00", 329.0, 100.0, "144:noise_suppressed"),
            ("2026-05-24 13:00:00", 520.0, 80.0, "144"),
        ]:
            session.add(
                Reading(
                    date=date,
                    id="probe",
                    temperature=22.0,
                    litres_remaining=litres,
                    air_gap_cm=ag,
                    refill_detected="n",
                    leak_detected="n",
                    raw_flags=flags,
                )
            )
        await session.commit()


async def test_consumption_window_excludes_noise_suppressed(
    sf: async_sessionmaker,
) -> None:
    await _seed_noise_window(sf)
    rows = await _readings_in_window(
        sf,
        datetime(2026, 5, 24, 11, 0, 0),
        datetime(2026, 5, 24, 14, 0, 0),
    )
    assert len(rows) == 2
    assert all("noise_suppressed" not in (r.raw_flags or "") for r in rows)


async def test_cost_window_excludes_noise_suppressed(sf: async_sessionmaker) -> None:
    await _seed_noise_window(sf)
    rows = await _readings_between(
        sf, "2026-05-24 11:00:00", "2026-05-24 14:00:00"
    )
    assert len(rows) == 2
    assert all("noise_suppressed" not in (r.raw_flags or "") for r in rows)


async def test_apprise_fetch_excludes_noise_suppressed(
    sf: async_sessionmaker,
) -> None:
    await _seed_noise_window(sf)
    rows = await _fetch_readings_between(
        sf, "2026-05-24 11:00:00", "2026-05-24 14:00:00"
    )
    assert len(rows) == 2


async def test_window_keeps_legacy_rows_with_null_raw_flags(
    sf: async_sessionmaker,
) -> None:
    """Migrated v1 rows have raw_flags=NULL — those are not noise and
    must survive the filter."""
    async with sf() as session:
        session.add(
            Reading(
                date="2024-01-01 12:00:00",
                id="legacy",
                temperature=10.0,
                litres_remaining=900.0,
                air_gap_cm=30.0,
                refill_detected="n",
                leak_detected="n",
                raw_flags=None,
            )
        )
        await session.commit()
    rows = await _readings_in_window(
        sf,
        datetime(2024, 1, 1, 11, 0, 0),
        datetime(2024, 1, 1, 13, 0, 0),
    )
    assert len(rows) == 1
