"""Regression tests for two live-ingest bugs caught on the first real reading.

1. `litres_used_since_last` collapsed to 0 because the previous-reading
   lookup matched rows at-or-after the new payload's timestamp.
2. `current_ppl` / `cost_used` / `cost_to_fill` collapsed to 0 because the
   ingest path didn't pass a price into RecalcContext.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.ingest.mqtt import handle_payload
from kerotrack.models.reading import Reading
from kerotrack.publish.mqtt_publisher import MqttPublisher
from kerotrack.pubsub.bus import PubSubBus


pytestmark = pytest.mark.asyncio


class _Recorder:
    def __init__(self) -> None:
        self.calls = []

    async def publish(self, topic, body, *, qos=0, retain=False):
        self.calls.append((topic, body, retain))


async def _seed_old(sf: async_sessionmaker, *, date: str, litres: float, gap: float) -> None:
    async with sf() as session:
        session.add(
            Reading(
                date=date,
                id="probe",
                litres_remaining=litres,
                air_gap_cm=gap,
                temperature=10.0,
                refill_detected="n",
                leak_detected="n",
            )
        )
        await session.commit()


async def test_previous_reading_lookup_uses_strictly_earlier_rows(
    sf: async_sessionmaker, seeded_settings
) -> None:
    # Pre-seed a row at the SAME timestamp the new payload will use.
    same = "2026-04-26 07:07:03"
    await _seed_old(sf, date=same, litres=549.8, gap=76.0)

    # Older row that should be the actual "previous" comparator.
    await _seed_old(sf, date="2026-04-19 12:00:00", litres=900.0, gap=40.0)

    raw = {
        "time": same,
        "model": "Oil-SonicAdv",
        "id": 5434428,
        "depth_cm": 76.0,
        "temperature_C": 5.0,
    }
    rec = _Recorder()
    pub = MqttPublisher(client=rec)
    bus = PubSubBus()

    out = await handle_payload(
        raw,
        sf=sf,
        settings_service=seeded_settings,
        publisher=pub,
        pubsub=bus,
    )
    # Previous comparison should be the older 900 L row, NOT the same-ts
    # row we pre-seeded — so used > 0.
    assert out["litres_used_since_last"] > 0


async def test_price_provider_populates_cost_fields(
    sf: async_sessionmaker, seeded_settings
) -> None:
    raw = {
        "time": "2026-04-26 08:00:00",
        "model": "Oil-SonicAdv",
        "id": 5434428,
        "depth_cm": 76.0,
        "temperature_C": 5.0,
    }
    rec = _Recorder()
    pub = MqttPublisher(client=rec)
    bus = PubSubBus()

    async def _fixed_price() -> float:
        return 56.18

    out = await handle_payload(
        raw,
        sf=sf,
        settings_service=seeded_settings,
        publisher=pub,
        pubsub=bus,
        price_provider=_fixed_price,
    )
    assert out["current_ppl"] == 56.18
    assert out["cost_to_fill"] != "0.00"
    assert out["cost_used"] != ""


async def test_price_provider_failure_falls_back_to_zero_cost(
    sf: async_sessionmaker, seeded_settings
) -> None:
    raw = {
        "time": "2026-04-26 08:00:00",
        "model": "Oil-SonicAdv",
        "id": 5434428,
        "depth_cm": 76.0,
        "temperature_C": 5.0,
    }
    rec = _Recorder()
    pub = MqttPublisher(client=rec)
    bus = PubSubBus()

    async def _broken_price() -> float:
        raise RuntimeError("scraper down")

    out = await handle_payload(
        raw,
        sf=sf,
        settings_service=seeded_settings,
        publisher=pub,
        pubsub=bus,
        price_provider=_broken_price,
    )
    # Graceful degradation — payload still ingested, cost shown as 0.00.
    assert out["cost_to_fill"] == "0.00"
    assert out["current_ppl"] == 0.0
