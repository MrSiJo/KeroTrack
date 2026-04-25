"""MQTT publisher for the v1-compatible topics.

Wraps an aiomqtt client and exposes typed publish helpers. The client is
owned by the ingest task (one connection for sub + pub) — `MqttPublisher`
holds a reference to whatever the lifespan plumbed in.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class _Publishable(Protocol):
    async def publish(
        self, topic: str, payload: str | bytes, *, qos: int = 0, retain: bool = False
    ) -> Any:
        ...


class MqttPublisher:
    """Publishes to oiltank/level, oiltank/analysis, oiltank/cost_analysis.

    `client` is duck-typed: anything with `publish(topic, payload, retain=)`
    works (used by the test suite to inject a recorder).
    """

    def __init__(
        self,
        *,
        client: _Publishable,
        topic_level: str = "oiltank/level",
        topic_analysis: str = "oiltank/analysis",
        topic_costanalysis: str = "oiltank/cost_analysis",
    ) -> None:
        self._client = client
        self._topic_level = topic_level
        self._topic_analysis = topic_analysis
        self._topic_costanalysis = topic_costanalysis

    async def publish_level(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload)
        await self._client.publish(self._topic_level, body, retain=True)

    async def publish_analysis(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload)
        await self._client.publish(self._topic_analysis, body, retain=True)

    async def publish_costanalysis(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload)
        await self._client.publish(self._topic_costanalysis, body, retain=True)
