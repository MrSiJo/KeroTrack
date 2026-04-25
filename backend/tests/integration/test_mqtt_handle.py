"""End-to-end ingest pipeline test (without a real broker)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.ingest.mqtt import handle_payload
from kerotrack.models.reading import Reading
from kerotrack.publish.mqtt_publisher import MqttPublisher
from kerotrack.pubsub.bus import PubSubBus


FIXTURES = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "watchman_sonic_payloads.json").read_text()
)


class _RecorderClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    async def publish(self, topic: str, payload: str, *, qos: int = 0, retain: bool = False) -> Any:
        self.calls.append((topic, payload, retain))


pytestmark = pytest.mark.asyncio


async def test_handle_payload_persists_and_publishes(
    sf: async_sessionmaker, seeded_settings,
) -> None:
    rec = _RecorderClient()
    pub = MqttPublisher(client=rec)
    bus = PubSubBus()
    sub = bus.subscribe("reading")

    processed = await handle_payload(
        FIXTURES["canonical"],
        sf=sf,
        settings_service=seeded_settings,
        publisher=pub,
        pubsub=bus,
    )

    # Persisted exactly one row.
    async with sf() as session:
        rows = (await session.execute(select(Reading))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.date == processed["date"]
    assert row.id == str(processed["id"])
    assert row.cost_to_fill == processed["cost_to_fill"]

    # Published to oiltank/level.
    assert rec.calls and rec.calls[0][0] == "oiltank/level"
    body = json.loads(rec.calls[0][1])
    assert body["litres_remaining"] == processed["litres_remaining"]

    # Pubsub fanned out.
    channel, payload = await sub.get()
    assert channel == "reading"
    assert payload["id"] == processed["id"]


async def test_handle_payload_idempotent_on_duplicate(
    sf: async_sessionmaker, seeded_settings,
) -> None:
    rec = _RecorderClient()
    pub = MqttPublisher(client=rec)
    bus = PubSubBus()
    await handle_payload(
        FIXTURES["canonical"],
        sf=sf, settings_service=seeded_settings, publisher=pub, pubsub=bus,
    )
    await handle_payload(
        FIXTURES["canonical"],
        sf=sf, settings_service=seeded_settings, publisher=pub, pubsub=bus,
    )
    async with sf() as session:
        count = len((await session.execute(select(Reading.date))).all())
    assert count == 1


async def test_handle_payload_uses_previous_reading(
    sf: async_sessionmaker, seeded_settings,
) -> None:
    rec = _RecorderClient()
    pub = MqttPublisher(client=rec)
    bus = PubSubBus()

    first = await handle_payload(
        FIXTURES["canonical"],
        sf=sf, settings_service=seeded_settings, publisher=pub, pubsub=bus,
    )
    second = await handle_payload(
        FIXTURES["warm_with_history"],
        sf=sf, settings_service=seeded_settings, publisher=pub, pubsub=bus,
    )

    assert second["litres_used_since_last"] >= 0
    # Air gap grew → previous level was higher → some litres used (or 0 if cooler).
    assert "refill_detected" in second
