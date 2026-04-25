"""SSE endpoint backed by the in-process pubsub bus."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/api/stream", tags=["stream"])


_DEFAULT_CHANNELS = ("reading", "analysis", "cost_analysis", "mqtt_message")


@router.get("")
async def stream(
    request: Request,
    channels: str = Query(default=",".join(_DEFAULT_CHANNELS)),
) -> EventSourceResponse:
    bus = request.app.state.pubsub
    chans = [c.strip() for c in channels.split(",") if c.strip()]

    async def event_source() -> AsyncIterator[dict[str, str]]:
        queues = [bus.subscribe(c) for c in chans]
        try:
            while True:
                if await request.is_disconnected():
                    return
                # Race the queues with a small timeout so disconnect is detected.
                gets = [asyncio.create_task(q.get()) for q in queues]
                done, pending = await asyncio.wait(
                    gets,
                    timeout=15.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                if not done:
                    yield {"event": "ping", "data": "{}"}
                    continue
                for t in done:
                    channel, payload = t.result()
                    yield {"event": channel, "data": json.dumps(payload, default=str)}
        finally:
            for c, q in zip(chans, queues, strict=True):
                bus.unsubscribe(c, q)

    return EventSourceResponse(event_source())
