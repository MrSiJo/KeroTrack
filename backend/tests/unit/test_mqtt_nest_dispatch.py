"""MQTT ingest routes Nest heating messages by topic (synthetic data)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.ingest.mqtt import MqttIngest
from kerotrack.models.nest_heating_daily import NestHeatingDaily
from kerotrack.models.reading import Reading
from kerotrack.pubsub.bus import PubSubBus

pytestmark = pytest.mark.asyncio


async def test_nest_topic_is_dispatched_to_nest_store(
    sf: async_sessionmaker, seeded_settings
) -> None:
    ingest = MqttIngest(sf=sf, settings_service=seeded_settings, pubsub=PubSubBus())
    ingest._nest_topic = "kerotrack/nest_heating"
    await ingest._dispatch("kerotrack/nest_heating", {"date": "2026-01-05", "heating_hours": 3.0})
    # An invalid Nest payload is dropped, and does not reach the readings path.
    await ingest._dispatch("kerotrack/nest_heating", {"date": "bad", "heating_hours": 3.0})
    async with sf() as session:
        nest = (await session.execute(select(NestHeatingDaily))).scalars().all()
        readings = (await session.execute(select(Reading))).scalars().all()
    assert [(r.date, r.heating_hours) for r in nest] == [("2026-01-05", 3.0)]
    assert readings == []


async def test_other_topics_ignore_nest_shape(sf: async_sessionmaker, seeded_settings) -> None:
    ingest = MqttIngest(sf=sf, settings_service=seeded_settings, pubsub=PubSubBus())
    ingest._nest_topic = "kerotrack/nest_heating"
    await ingest._dispatch("lilygo/x/RTL_433toMQTT/Oil-SonicAdv/1", {"date": "2026-01-05", "heating_hours": 3.0})
    async with sf() as session:
        assert (await session.execute(select(NestHeatingDaily))).scalars().all() == []


async def test_subscribe_topics_include_nest(sf: async_sessionmaker, seeded_settings) -> None:
    ingest = MqttIngest(sf=sf, settings_service=seeded_settings, pubsub=PubSubBus())
    topics = await ingest._subscribe_topics()
    assert topics[0] == str(await seeded_settings.get("mqtt.topic_readings"))
    assert "kerotrack/nest_heating" in topics


class _Msg:
    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = topic
        self.payload = payload


class _FakeClient:
    def __init__(self, msgs: list[_Msg]) -> None:
        self._msgs = msgs

    @property
    def messages(self):
        async def gen():
            for m in self._msgs:
                yield m

        return gen()


async def test_non_json_nest_payload_warns_without_echo(
    sf: async_sessionmaker, seeded_settings, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    ingest = MqttIngest(sf=sf, settings_service=seeded_settings, pubsub=PubSubBus())
    ingest._nest_topic = "kerotrack/nest_heating"
    await ingest._consume(_FakeClient([_Msg("kerotrack/nest_heating", b"secret-ish 7.5")]))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings
    assert "7.5" not in caplog.text


async def test_nest_topic_equal_to_readings_topic_is_ignored(
    sf: async_sessionmaker, seeded_settings, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    readings_topic = str(await seeded_settings.get("mqtt.topic_readings"))
    await seeded_settings.set("mqtt.topic_nest_heating", readings_topic)
    caplog.set_level(logging.WARNING, logger="kerotrack.ingest.mqtt")
    ingest = MqttIngest(sf=sf, settings_service=seeded_settings, pubsub=PubSubBus())
    topics = await ingest._subscribe_topics()
    assert topics == [readings_topic]
    assert ingest._nest_topic is None
    assert sum(r.levelno == logging.WARNING for r in caplog.records) == 1
