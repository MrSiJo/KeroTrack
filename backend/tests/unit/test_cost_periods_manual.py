"""Cost periods anchored on the operator's refill log (spec A7, A8).

Period boundaries come from ``actual_refill_costs.refill_date``. Each log
date snaps to the real level jump in [date - 14 d, date + 3 d]: the first
reading (noise rows included) rising more than the refill threshold over
the last trusted level, confirmed by the first trusted reading at/after it
still being that far up. The boundary is that trusted reading. With no
jump, the first trusted reading within 3 days after the log date is used;
otherwise the entry is skipped (logs that predate the readings).

A sensor ``refill_detected == "y"`` flag only becomes a boundary when there
is no manual entry within 7 days, the flagged reading is trusted, and the
level stays up for the next 24 h. Boundaries within a day collapse onto the
earlier. Stale ``refill_periods`` rows are deleted once a run writes at
least one period.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.cost import _detect_periods, _period_boundaries, compute
from kerotrack.clock import local_now, parse_local
from kerotrack.models.reading import NOISE_SUPPRESSED_SENTINEL, Reading
from kerotrack.models.refill import ActualRefillCost
from kerotrack.models.refill_period import RefillPeriod


pytestmark = pytest.mark.asyncio

FMT = "%Y-%m-%d %H:%M:%S"


def _days_since(when: str) -> int:
    dt = parse_local(when)
    assert dt is not None
    return int(max((local_now() - dt).total_seconds() / 86400.0, 0.0))


async def _seed_production_shape(sf: async_sessionmaker) -> None:
    """2025 at 12 h cadence, falling 1 L per reading from 900 L.

    - 2025-01-01: manual refill (logged).
    - 2025-05-07: real refill to 1100 L; the jump reading is noise
      suppressed so the sensor never flagged it, but it is logged.
    - 2025-09-01: false sensor refill flag, +150 L that drops back
      within 6 h.
    """
    start = datetime(2025, 1, 1, 0, 0, 0)
    refill_at = datetime(2025, 5, 7, 0, 0, 0)
    false_flag_at = datetime(2025, 9, 1, 0, 0, 0)
    end = datetime(2025, 12, 31, 12, 0, 0)

    async with sf() as session:
        when = start
        level = 900.0
        while when <= end:
            raw_flags = None
            refill_detected = "n"
            litres = level
            if when == refill_at:
                level = 1100.0
                litres = level
                raw_flags = NOISE_SUPPRESSED_SENTINEL
            elif when == false_flag_at:
                litres = level + 150.0
                refill_detected = "y"
            session.add(
                Reading(
                    date=when.strftime(FMT),
                    id="probe",
                    litres_remaining=litres,
                    current_ppl=60.0,
                    refill_detected=refill_detected,
                    leak_detected="n",
                    raw_flags=raw_flags,
                )
            )
            if when == false_flag_at:
                # Drops straight back within 6 h: flapping, not a refill.
                session.add(
                    Reading(
                        date=(when + timedelta(hours=6)).strftime(FMT),
                        id="probe",
                        litres_remaining=level - 0.5,
                        current_ppl=60.0,
                        refill_detected="n",
                        leak_detected="n",
                    )
                )
            level -= 1.0
            when += timedelta(hours=12)

        session.add(
            ActualRefillCost(
                refill_date="2025-01-01 00:00:00",
                actual_volume_litres=600.0,
                actual_ppl=55.0,
                total_cost=330.0,
            )
        )
        session.add(
            ActualRefillCost(
                refill_date="2025-05-07 12:00:00",
                actual_volume_litres=500.0,
                actual_ppl=56.79,
                total_cost=298.0,
            )
        )
        # The bogus period a sensor-only run would have written.
        session.add(
            RefillPeriod(
                start_date="2025-05-07 12:00:00",
                end_date="2025-09-01 00:00:00",
                days=117,
                total_consumption=10.0,
                total_cost=6.0,
            )
        )
        await session.commit()


async def test_boundaries_follow_refill_log_not_sensor_flapping(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_production_shape(sf)

    boundaries = await _period_boundaries(sf)

    assert boundaries == ["2025-01-01 00:00:00", "2025-05-07 12:00:00"]


async def test_detect_periods_rebuilds_table_from_refill_log(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_production_shape(sf)

    written = await _detect_periods(sf, seeded_settings)

    assert written == 1
    async with sf() as session:
        rows = (await session.execute(select(RefillPeriod))).scalars().all()
    assert [(r.start_date, r.end_date) for r in rows] == [
        ("2025-01-01 00:00:00", "2025-05-07 12:00:00")
    ]
    row = rows[0]
    # Net consumption 900 -> 649 (last trusted reading before the boundary).
    assert row.total_consumption == pytest.approx(251.0)
    assert row.used_actual_cost == 1
    assert row.refill_amount_liters == pytest.approx(500.0)
    assert row.refill_ppl == pytest.approx(56.79)
    assert row.refill_cost == pytest.approx(298.0)


async def test_cost_payload_days_since_refill_and_period_end(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_production_shape(sf)
    await _detect_periods(sf, seeded_settings)

    payload = await compute(sf, seeded_settings)

    assert payload is not None
    assert payload["days_since_refill"] == _days_since("2025-05-07 12:00:00")
    assert payload["days_since_period_end"] == _days_since(payload["latest_period_end"])
    assert payload["latest_period_end"] == "2025-05-07 12:00:00"


async def test_manual_date_maps_to_first_trusted_reading_after_it(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """A logged refill date between readings snaps to the next trusted one,
    skipping noise suppressed rows."""
    async with sf() as session:
        session.add(
            Reading(date="2025-03-01 09:00:00", id="probe", litres_remaining=500.0)
        )
        session.add(
            Reading(
                date="2025-03-01 15:00:00",
                id="probe",
                litres_remaining=1400.0,
                raw_flags=NOISE_SUPPRESSED_SENTINEL,
            )
        )
        session.add(
            Reading(date="2025-03-01 21:00:00", id="probe", litres_remaining=1000.0)
        )
        session.add(ActualRefillCost(refill_date="2025-03-01 12:00:00"))
        # Logged after the last reading: no post-refill level, skipped.
        session.add(ActualRefillCost(refill_date="2025-04-01 12:00:00"))
        await session.commit()

    assert await _period_boundaries(sf) == ["2025-03-01 21:00:00"]


async def _seed_sensor_refill(
    sf: async_sessionmaker,
    *,
    flag_date: str = "2025-06-01 09:00:00",
    raw_flags: str | None = None,
    after_litres: float = 1095.0,
) -> None:
    """Pre-refill reading, a flagged 1100 L reading, and one 12 h later."""
    flag_dt = datetime.strptime(flag_date, FMT)
    async with sf() as session:
        session.add(
            Reading(
                date=(flag_dt - timedelta(hours=12)).strftime(FMT),
                id="probe",
                litres_remaining=300.0,
                refill_detected="n",
            )
        )
        session.add(
            Reading(
                date=flag_date,
                id="probe",
                litres_remaining=1100.0,
                refill_detected="y",
                raw_flags=raw_flags,
            )
        )
        session.add(
            Reading(
                date=(flag_dt + timedelta(hours=12)).strftime(FMT),
                id="probe",
                litres_remaining=after_litres,
                refill_detected="n",
            )
        )
        await session.commit()


async def test_sensor_refill_without_log_entry_is_a_boundary(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_sensor_refill(sf)
    assert await _period_boundaries(sf) == ["2025-06-01 09:00:00"]


async def test_sensor_refill_needs_a_confirming_reading(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """A flag on the newest reading can't be shown to stay up yet."""
    async with sf() as session:
        session.add(
            Reading(
                date="2025-06-01 09:00:00",
                id="probe",
                litres_remaining=1100.0,
                refill_detected="y",
            )
        )
        await session.commit()
    assert await _period_boundaries(sf) == []


async def test_noise_suppressed_sensor_flag_is_not_a_boundary(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_sensor_refill(sf, raw_flags=NOISE_SUPPRESSED_SENTINEL)
    assert await _period_boundaries(sf) == []


async def test_sensor_flag_that_falls_back_is_not_a_boundary(
    sf: async_sessionmaker, seeded_settings
) -> None:
    # Falls 400 L within 24 h; refill threshold default is 100 L.
    await _seed_sensor_refill(sf, after_litres=700.0)
    assert await _period_boundaries(sf) == []


async def test_sensor_flag_near_log_entry_defers_to_the_log(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """A sensor flag that would pass on its own (trusted, holds 24 h) is
    dropped when a logged refill sits within 7 days of it."""
    async with sf() as session:
        for date, litres, flag in (
            ("2025-05-20 09:00:00", 300.0, "n"),
            ("2025-05-20 21:00:00", 1100.0, "n"),  # real jump, unflagged
            ("2025-05-21 09:00:00", 1095.0, "n"),
            ("2025-05-26 09:00:00", 1060.0, "n"),
            ("2025-05-26 21:00:00", 1250.0, "y"),  # 6 days after the log
            ("2025-05-27 09:00:00", 1245.0, "n"),
        ):
            session.add(
                Reading(
                    date=date, id="probe", litres_remaining=litres, refill_detected=flag
                )
            )
        session.add(ActualRefillCost(refill_date="2025-05-20 12:00:00"))
        await session.commit()
    assert await _period_boundaries(sf) == ["2025-05-20 21:00:00"]


async def _seed_falling(
    sf: async_sessionmaker,
    start: datetime,
    end: datetime,
    *,
    jump_at: datetime | None = None,
    jump_noise_suppressed: bool = False,
) -> None:
    """Readings every 12 h falling 1 L each, optionally jumping to 1100 L."""
    async with sf() as session:
        when = start
        level = 400.0
        while when <= end:
            raw_flags = None
            if jump_at is not None and when == jump_at:
                level = 1100.0
                if jump_noise_suppressed:
                    raw_flags = NOISE_SUPPRESSED_SENTINEL
            session.add(
                Reading(
                    date=when.strftime(FMT),
                    id="probe",
                    litres_remaining=level,
                    refill_detected="n",
                    raw_flags=raw_flags,
                )
            )
            level -= 1.0
            when += timedelta(hours=12)
        await session.commit()


async def test_log_date_after_the_jump_snaps_back_to_the_jump(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """Owner logged the invoice date 12 days after a noise-suppressed jump:
    the boundary is the first trusted reading after the jump."""
    await _seed_falling(
        sf,
        datetime(2025, 4, 1),
        datetime(2025, 6, 1),
        jump_at=datetime(2025, 4, 25, 12, 0, 0),
        jump_noise_suppressed=True,
    )
    async with sf() as session:
        session.add(ActualRefillCost(refill_date="2025-05-07 12:00:00"))
        await session.commit()
    assert await _period_boundaries(sf) == ["2025-04-26 00:00:00"]


async def test_reverting_noise_spike_is_not_taken_as_the_jump(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """A +180 L noise-suppressed spike 10 days before the log date reverts
    within hours; the real persistent jump 2 days before the log wins."""
    await _seed_falling(
        sf,
        datetime(2025, 4, 1),
        datetime(2025, 6, 1),
        jump_at=datetime(2025, 5, 5, 12, 0, 0),
    )
    async with sf() as session:
        # Falling series reads 347 L at 2025-04-27 12:00 (previous reading).
        session.add(
            Reading(
                date="2025-04-27 21:00:00",
                id="probe",
                litres_remaining=347.0 + 180.0,
                refill_detected="n",
                raw_flags=NOISE_SUPPRESSED_SENTINEL,
            )
        )
        session.add(ActualRefillCost(refill_date="2025-05-07 12:00:00"))
        await session.commit()
    assert await _period_boundaries(sf) == ["2025-05-05 12:00:00"]


async def _add_noise_dip(sf: async_sessionmaker, date: str, litres: float) -> None:
    async with sf() as session:
        session.add(
            Reading(
                date=date,
                id="probe",
                litres_remaining=litres,
                refill_detected="n",
                raw_flags=NOISE_SUPPRESSED_SENTINEL,
            )
        )
        await session.commit()


async def test_noise_dip_recovery_is_not_taken_as_the_jump(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """A phantom 150 L dip (noise suppressed) then a normal trusted reading
    rises > threshold over the dip, not over the last trusted level; the
    real persistent jump wins."""
    await _seed_falling(
        sf,
        datetime(2025, 4, 1),
        datetime(2025, 6, 1),
        jump_at=datetime(2025, 5, 5, 12, 0, 0),
    )
    # Trusted series reads 347 L at 2025-04-27 12:00 and 346 L at 04-28 00:00.
    await _add_noise_dip(sf, "2025-04-27 21:00:00", 347.0 - 150.0)
    async with sf() as session:
        session.add(ActualRefillCost(refill_date="2025-05-07 12:00:00"))
        await session.commit()
    assert await _period_boundaries(sf) == ["2025-05-05 12:00:00"]


async def test_noise_dip_alone_falls_back_to_the_log_date(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """Only the dip and no real jump: the existing no-jump rule applies
    (first trusted reading within 3 days after the log date)."""
    await _seed_falling(sf, datetime(2025, 4, 1), datetime(2025, 6, 1))
    await _add_noise_dip(sf, "2025-04-27 21:00:00", 347.0 - 150.0)
    async with sf() as session:
        session.add(ActualRefillCost(refill_date="2025-05-07 12:00:00"))
        await session.commit()
    assert await _period_boundaries(sf) == ["2025-05-07 12:00:00"]


async def test_log_entry_before_any_reading_is_skipped(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """Refills logged years before the sensor existed must not collapse onto
    the first ever reading."""
    await _seed_falling(sf, datetime(2023, 6, 2), datetime(2023, 7, 1))
    async with sf() as session:
        session.add(ActualRefillCost(refill_date="2019-08-15 12:00:00"))
        session.add(ActualRefillCost(refill_date="2023-02-20 12:00:00"))
        await session.commit()
    assert await _period_boundaries(sf) == []


async def test_log_date_without_jump_uses_reading_within_three_days(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_falling(sf, datetime(2025, 3, 12, 9, 0, 0), datetime(2025, 4, 1))
    async with sf() as session:
        session.add(ActualRefillCost(refill_date="2025-03-10 12:00:00"))
        await session.commit()
    assert await _period_boundaries(sf) == ["2025-03-12 09:00:00"]


async def test_log_date_without_jump_or_nearby_reading_is_skipped(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """Readings resume 5 days after the log date, no jump: skipped."""
    await _seed_falling(sf, datetime(2025, 3, 15, 12, 0, 0), datetime(2025, 4, 1))
    async with sf() as session:
        session.add(ActualRefillCost(refill_date="2025-03-10 12:00:00"))
        await session.commit()
    assert await _period_boundaries(sf) == []


async def test_boundaries_within_a_day_keep_the_earlier(
    sf: async_sessionmaker, seeded_settings
) -> None:
    async with sf() as session:
        for date in ("2025-02-01 08:00:00", "2025-02-01 20:00:00", "2025-02-10 08:00:00"):
            session.add(Reading(date=date, id="probe", litres_remaining=800.0))
        session.add(ActualRefillCost(refill_date="2025-02-01 08:00:00"))
        session.add(ActualRefillCost(refill_date="2025-02-01 20:00:00"))
        session.add(ActualRefillCost(refill_date="2025-02-10 08:00:00"))
        await session.commit()
    assert await _period_boundaries(sf) == [
        "2025-02-01 08:00:00",
        "2025-02-10 08:00:00",
    ]


async def test_days_since_refill_falls_back_to_latest_boundary(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """No log entries at all: count from the latest accepted boundary."""
    await _seed_sensor_refill(sf, flag_date="2025-06-01 09:00:00")
    await _seed_sensor_refill(sf, flag_date="2025-07-01 09:00:00")
    await _detect_periods(sf, seeded_settings)

    payload = await compute(sf, seeded_settings)

    assert payload is not None
    assert payload["days_since_refill"] == _days_since("2025-07-01 09:00:00")
    assert payload["days_since_period_end"] == _days_since("2025-07-01 09:00:00")
