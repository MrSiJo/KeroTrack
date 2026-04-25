"""Recent MQTT events ring buffer (in-memory, populated by ingest)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/mqtt-feed", tags=["mqtt"])


class MqttFeedRing:
    def __init__(self, *, capacity: int = 200) -> None:
        self._items: deque[dict[str, Any]] = deque(maxlen=capacity)

    def append(self, *, topic: str, payload: Any) -> None:
        self._items.append(
            {"topic": topic, "payload": payload, "ts": time.time()}
        )

    def snapshot(self, *, limit: int) -> list[dict[str, Any]]:
        items = list(self._items)
        return items[-limit:]


@router.get("")
async def feed(
    request: Request, limit: int = Query(default=50, ge=1, le=500)
) -> dict[str, list[dict[str, Any]]]:
    ring: MqttFeedRing | None = getattr(request.app.state, "mqtt_feed", None)
    if ring is None:
        return {"items": []}
    return {"items": list(reversed(ring.snapshot(limit=limit)))}
