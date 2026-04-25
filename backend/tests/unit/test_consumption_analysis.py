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
