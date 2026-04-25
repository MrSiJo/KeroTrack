"""MQTT publisher unit tests — golden-path payload shape."""

from __future__ import annotations

import json
from typing import Any

import pytest

from kerotrack.publish.mqtt_publisher import MqttPublisher


class _RecorderClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    async def publish(
        self, topic: str, payload: str | bytes, *, qos: int = 0, retain: bool = False
    ) -> Any:
        self.calls.append(
            (topic, payload.decode() if isinstance(payload, bytes) else payload, retain)
        )


pytestmark = pytest.mark.asyncio


async def test_publish_level_uses_topic_and_retain() -> None:
    rec = _RecorderClient()
    pub = MqttPublisher(client=rec)
    await pub.publish_level({"id": 1, "litres_remaining": 800.0, "cost_to_fill": "100.50"})
    assert len(rec.calls) == 1
    topic, body, retain = rec.calls[0]
    assert topic == "oiltank/level"
    assert retain is True
    parsed = json.loads(body)
    assert parsed["litres_remaining"] == 800.0
    assert parsed["cost_to_fill"] == "100.50"


async def test_publish_analysis_uses_correct_topic() -> None:
    rec = _RecorderClient()
    pub = MqttPublisher(client=rec)
    await pub.publish_analysis({"estimated_days_remaining": 42.0})
    assert rec.calls[0][0] == "oiltank/analysis"


async def test_publish_costanalysis_uses_underscore_topic() -> None:
    rec = _RecorderClient()
    pub = MqttPublisher(client=rec)
    await pub.publish_costanalysis({"analysis_date": "2026-04-25"})
    assert rec.calls[0][0] == "oiltank/cost_analysis"


async def test_topic_overrides_apply() -> None:
    rec = _RecorderClient()
    pub = MqttPublisher(
        client=rec,
        topic_level="custom/level",
        topic_analysis="custom/analysis",
        topic_costanalysis="custom/cost",
    )
    await pub.publish_level({"x": 1})
    await pub.publish_analysis({"y": 2})
    await pub.publish_costanalysis({"z": 3})
    topics = [c[0] for c in rec.calls]
    assert topics == ["custom/level", "custom/analysis", "custom/cost"]
