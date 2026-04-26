"""Consumption analysis output shape + persistence."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.consumption import compute, run_analysis
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
        # Refill from a year ago — tank topped up to ~1100 L.
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
        # 300 boring "no refill" rows over the year.
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
        # Latest reading.
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
    # days_since_refill must be ~365, not None.
    assert payload["days_since_refill"] is not None
    assert 360 <= payload["days_since_refill"] <= 366
    # total_consumption_since_refill should be ~ refill - latest = 550 L,
    # NOT a tiny window-only delta.
    assert 540.0 <= payload["total_consumption_since_refill"] <= 560.0
    # Avg daily ~ 550 / 365 ≈ 1.5 L/day (≥ MIN_CONSUMPTION_L_PER_DAY).
    assert payload["avg_daily_consumption_l"] > 1.0


async def test_anchor_falls_back_to_earliest_when_no_refill(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """No refill marker anywhere → days_since_refill is None,
    but the consumption window still spans earliest→latest so the
    average is meaningful."""
    await _seed_readings(sf, count=10)
    payload = await compute(sf, seeded_settings)
    assert payload is not None
    assert payload["days_since_refill"] is None
    assert payload["total_consumption_since_refill"] > 0
    assert payload["avg_daily_consumption_l"] > 0
