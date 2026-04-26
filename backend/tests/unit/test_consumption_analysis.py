"""Consumption analysis output shape, persistence, and v1 algorithm parity.

Covers the v1 algorithm restoration (backlog A1):
- Hot-water baseline floor on warm/zero-HDD days
- Bounded look-back (30-60 days) when post-refill window is long
- Heating estimate clamps (MIN 0.5 / MAX 15 L/day)
- Monthly seasonal heating factor table from real Nest hours data
- estimated_days_remaining cap (400 with HDD, 700 without)
- Per-pair refill-aware walker for total_consumption
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.consumption import (
    MAX_HEATING_L,
    MIN_HEATING_L,
    _hot_water_baseline_l_per_day,
    _seasonal_heating_factor,
    compute,
    run_analysis,
)
from kerotrack.models.hdd import HddDatum
from kerotrack.models.reading import Reading
from kerotrack.publish.mqtt_publisher import MqttPublisher
from kerotrack.pubsub.bus import PubSubBus


pytestmark = pytest.mark.asyncio


REQUIRED_KEYS = {
    "latest_reading_date",
    "latest_analysis_date",
    "latest_reading_refill_detected",
    "latest_reading_leak_detected",
    "days_since_refill",
    "total_consumption_since_refill",
    "avg_daily_consumption_l",
    "estimated_days_remaining",
    "estimated_empty_date",
    "consumption_per_hdd_l",
    "upcoming_month_hdd",
    "estimated_daily_consumption_hdd_l",
    "estimated_daily_hot_water_consumption_l",
    "estimated_daily_heating_consumption_l",
    "seasonal_heating_factor",
    "remaining_days_empty_hdd",
    "remaining_date_empty_hdd",
}


async def _seed_readings(sf: async_sessionmaker, count: int = 10) -> None:
    async with sf() as session:
        for i in range(count):
            session.add(
                Reading(
                    date=f"2026-04-{15 + i:02d} 12:00:00",
                    id="probe",
                    temperature=12.0 + i * 0.1,
                    litres_remaining=1000.0 - i * 5.0,
                    air_gap_cm=40.0 + i * 0.5,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
        await session.commit()


async def test_compute_returns_full_payload(sf: async_sessionmaker, seeded_settings) -> None:
    await _seed_readings(sf)
    payload = await compute(sf, seeded_settings)
    assert payload is not None
    assert REQUIRED_KEYS.issubset(payload.keys())


async def test_compute_returns_none_with_insufficient_data(
    sf: async_sessionmaker, seeded_settings
) -> None:
    payload = await compute(sf, seeded_settings)
    assert payload is None


async def test_run_analysis_persists_and_publishes(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_readings(sf)

    class Recorder:
        calls = []

        async def publish(self, topic, body, *, qos=0, retain=False):
            type(self).calls.append((topic, body, retain))

    rec = Recorder()
    publisher = MqttPublisher(client=rec)
    bus = PubSubBus()
    sub = bus.subscribe("analysis")

    payload = await run_analysis(
        sf=sf, settings_service=seeded_settings, publisher=publisher, pubsub=bus
    )
    assert payload is not None
    assert Recorder.calls and Recorder.calls[0][0] == "oiltank/analysis"
    channel, body = await sub.get()
    assert channel == "analysis"
    assert body["estimated_days_remaining"] == payload["estimated_days_remaining"]


async def test_anchor_finds_refill_far_outside_recent_window(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """A refill from a year ago must still anchor 'since refill' totals,
    even if there are thousands of newer readings on top."""
    async with sf() as session:
        session.add(
            Reading(
                date="2025-04-26 09:00:00",
                id="probe",
                litres_remaining=1100.0,
                air_gap_cm=20.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        for i in range(300):
            session.add(
                Reading(
                    date=f"2025-{(i % 12) + 1:02d}-{(i % 27) + 1:02d} {(i % 23):02d}:00:00",
                    id="probe",
                    litres_remaining=1100.0 - (i * 1.5),
                    air_gap_cm=20.0 + i * 0.05,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
        session.add(
            Reading(
                date="2026-04-26 09:00:00",
                id="probe",
                litres_remaining=550.0,
                air_gap_cm=77.0,
                refill_detected="n",
                leak_detected="n",
            )
        )
        await session.commit()

    payload = await compute(sf, seeded_settings)
    assert payload is not None
    assert payload["days_since_refill"] is not None
    assert 360 <= payload["days_since_refill"] <= 366
    assert 540.0 <= payload["total_consumption_since_refill"] <= 560.0
    assert payload["avg_daily_consumption_l"] > 1.0


async def test_anchor_falls_back_to_earliest_when_no_refill(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_readings(sf, count=10)
    payload = await compute(sf, seeded_settings)
    assert payload is not None
    assert payload["days_since_refill"] is None
    assert payload["total_consumption_since_refill"] > 0
    assert payload["avg_daily_consumption_l"] > 0


# --- A1: v1 algorithm parity --------------------------------------------------

async def test_seasonal_heating_factor_uses_real_nest_data() -> None:
    # Per v1 oil_analysis.get_seasonal_heating_factor — Nest hours / max(78).
    # January peak should be 1.0; June/July/August zero; April 21/78 ≈ 0.27.
    assert _seasonal_heating_factor(1) == pytest.approx(1.0)
    assert _seasonal_heating_factor(6) == pytest.approx(0.0)
    assert _seasonal_heating_factor(7) == pytest.approx(0.0)
    assert _seasonal_heating_factor(8) == pytest.approx(0.0)
    # April: 21/78
    assert _seasonal_heating_factor(4) == pytest.approx(21 / 78, abs=0.001)
    # November: 29/78
    assert _seasonal_heating_factor(11) == pytest.approx(29 / 78, abs=0.001)


async def test_hot_water_baseline_matches_v1_formula() -> None:
    # v1: (10 sessions/week × 0.5h × fuel_rate_l_per_h) / 7 × 1.1
    # With fuel_rate=2.33: (10 × 0.5 × 2.33) / 7 × 1.1 ≈ 1.831
    assert _hot_water_baseline_l_per_day(2.33) == pytest.approx(1.831, abs=0.01)
    # Doubling fuel rate doubles the baseline.
    assert _hot_water_baseline_l_per_day(4.66) == pytest.approx(3.661, abs=0.01)


async def test_hot_water_floor_applied_on_zero_hdd_summer_day(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """Summer day with HDD=0 and miniscule oil drop must not deflate
    avg_daily below the HW baseline."""
    async with sf() as session:
        # Refill anchor in mid-July.
        session.add(
            Reading(
                date="2026-07-01 09:00:00",
                id="probe",
                litres_remaining=1000.0,
                air_gap_cm=30.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        # 30 summer days, oil drops 0.3 L/day (well below HW baseline).
        for i in range(1, 31):
            session.add(
                Reading(
                    date=f"2026-07-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1000.0 - i * 0.3,
                    air_gap_cm=30.0 + i * 0.05,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
        # Zero HDD across the window.
        for i in range(31):
            session.add(HddDatum(date=f"2026-07-{i + 1:02d}", hdd=0.0))
        await session.commit()

    payload = await compute(sf, seeded_settings)
    assert payload is not None
    # HW baseline ≈ 1.83 L/day; avg must be ≥ that, not the raw 0.3 L/day.
    assert payload["avg_daily_consumption_l"] >= 1.5
    # No HDD → today_HDD=0 → heating clamped to zero.
    assert payload["estimated_daily_heating_consumption_l"] == pytest.approx(0.0)


async def test_heating_estimate_clamped_to_max(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """A spike on a single day shouldn't produce > MAX_HEATING_L heating."""
    async with sf() as session:
        # Refill, then a sequence with one extreme drop.
        session.add(
            Reading(
                date="2026-01-01 09:00:00",
                id="probe",
                litres_remaining=1000.0,
                air_gap_cm=30.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        # 7 days, very heavy heating — 50 L/day on cold days.
        for i in range(1, 8):
            session.add(
                Reading(
                    date=f"2026-01-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1000.0 - i * 50.0,
                    air_gap_cm=30.0 + i * 1.0,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
            session.add(HddDatum(date=f"2026-01-{i + 1:02d}", hdd=15.0))
        await session.commit()

    payload = await compute(sf, seeded_settings)
    assert payload is not None
    # Heating component is clamped between MIN and MAX.
    assert payload["estimated_daily_heating_consumption_l"] <= MAX_HEATING_L
    assert payload["estimated_daily_heating_consumption_l"] >= 0.0


async def test_estimated_days_remaining_capped_in_summer(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """When today_HDD=0 the cap is 700 days; with HDD>0 it's 400."""
    async with sf() as session:
        # Mid-summer, tiny consumption, lots of oil.
        session.add(
            Reading(
                date="2026-07-01 09:00:00",
                id="probe",
                litres_remaining=1200.0,
                air_gap_cm=20.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        for i in range(1, 31):
            session.add(
                Reading(
                    date=f"2026-07-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1200.0 - i * 0.1,
                    air_gap_cm=20.0 + i * 0.02,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
            session.add(HddDatum(date=f"2026-07-{i + 1:02d}", hdd=0.0))
        await session.commit()

    payload = await compute(sf, seeded_settings)
    assert payload is not None
    # Without the cap this would be many thousands of days.
    assert payload["estimated_days_remaining"] <= 700.0


async def test_per_pair_walker_ignores_refill_spikes(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """A mid-window refill spike must not zero-out total_consumption."""
    async with sf() as session:
        # Initial refill anchor.
        session.add(
            Reading(
                date="2026-02-01 09:00:00",
                id="probe",
                litres_remaining=400.0,
                air_gap_cm=80.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        # Steady consumption for 10 days.
        for i in range(1, 11):
            session.add(
                Reading(
                    date=f"2026-02-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=400.0 - i * 5.0,
                    air_gap_cm=80.0 + i * 0.5,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
            session.add(HddDatum(date=f"2026-02-{i + 1:02d}", hdd=12.0))
        # Mid-window REFILL (litres jumps up by 800).
        session.add(
            Reading(
                date="2026-02-12 09:00:00",
                id="probe",
                litres_remaining=1150.0,
                air_gap_cm=10.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        # More steady consumption after refill.
        for i in range(1, 6):
            session.add(
                Reading(
                    date=f"2026-02-{12 + i:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1150.0 - i * 5.0,
                    air_gap_cm=10.0 + i * 0.5,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
            session.add(HddDatum(date=f"2026-02-{12 + i:02d}", hdd=12.0))
        await session.commit()

    payload = await compute(sf, seeded_settings)
    assert payload is not None
    # Total since latest refill (which is 2026-02-12) should be ~25 L,
    # not the negative jump from the refill.
    assert payload["total_consumption_since_refill"] >= 20.0
    assert payload["total_consumption_since_refill"] <= 30.0
    # avg_daily must be positive and around 5 L/day.
    assert payload["avg_daily_consumption_l"] >= 1.5
