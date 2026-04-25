"""Lightweight async fan-out bus.

Each subscribe call returns an asyncio.Queue; publish puts the event onto
every queue. Slow consumers don't slow producers — full queues drop the
event for that consumer with a warning.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)


class PubSubBus:
    def __init__(self, *, queue_size: int = 64) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[str, list[asyncio.Queue[tuple[str, Any]]]] = {}

    def subscribe(self, channel: str) -> asyncio.Queue[tuple[str, Any]]:
        q: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.setdefault(channel, []).append(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue[tuple[str, Any]]) -> None:
        try:
            self._subscribers.get(channel, []).remove(q)
        except ValueError:
            pass

    async def publish(self, channel: str, payload: Any) -> None:
        for q in list(self._subscribers.get(channel, [])):
            try:
                q.put_nowait((channel, payload))
            except asyncio.QueueFull:
                logger.warning("pubsub queue full on channel %s — dropping event", channel)

    async def stream(self, channel: str) -> AsyncIterator[tuple[str, Any]]:
        q = self.subscribe(channel)
        try:
            while True:
                yield await q.get()
        finally:
            self.unsubscribe(channel, q)
