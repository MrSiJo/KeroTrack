"""Async MQTT ingest task.

Subscribes to the `mqtt.topic_readings` configured topic, normalises the
incoming Watchman Sonic Advanced JSON, runs `recalc.process()`, persists the
resulting row in `readings`, and publishes the v1-compatible payload via
`MqttPublisher` plus a pubsub fan-out for SSE consumers.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.ingest.recalc import (
    PreviousReading,
    RecalcContext,
    context_from_settings,
    process,
)
from kerotrack.models.reading import Reading
from kerotrack.publish.mqtt_publisher import MqttPublisher
from kerotrack.pubsub.bus import PubSubBus

logger = logging.getLogger(__name__)


async def _load_previous(sf: async_sessionmaker) -> PreviousReading | None:
    async with sf() as session:
        row = (
            await session.execute(
                select(Reading.date, Reading.litres_remaining, Reading.air_gap_cm)
                .order_by(desc(Reading.date))
                .limit(1)
            )
        ).first()
    if row is None or row.litres_remaining is None or row.air_gap_cm is None:
        return None
    try:
        ts = datetime.strptime(row.date, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return PreviousReading(
        date=ts,
        litres_remaining=float(row.litres_remaining),
        air_gap_cm=float(row.air_gap_cm),
    )


def _normalise_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Massage the RTL_433 payload into the shape `recalc.process` expects."""
    payload = dict(raw)
    if payload.get("model") == "Oil-SonicAdv":
        payload["model"] = "Oil-SonicSmart"
    if "time" not in payload:
        payload["time"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return payload


async def _persist_reading(
    sf: async_sessionmaker, processed: dict[str, Any]
) -> None:
    """Insert into `readings`. Tolerates duplicate (date, id) by skipping."""
    async with sf() as session:
        existing = (
            await session.execute(
                select(Reading.date)
                .where(
                    Reading.date == processed["date"],
                    Reading.id == str(processed["id"]),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        session.add(
            Reading(
                date=processed["date"],
                id=str(processed["id"]),
                temperature=processed.get("temperature"),
                litres_remaining=processed.get("litres_remaining"),
                litres_used_since_last=processed.get("litres_used_since_last"),
                percentage_remaining=processed.get("percentage_remaining"),
                oil_depth_cm=processed.get("oil_depth_cm"),
                air_gap_cm=processed.get("air_gap_cm"),
                current_ppl=processed.get("current_ppl"),
                cost_used=str(processed.get("cost_used") or ""),
                cost_to_fill=str(processed.get("cost_to_fill") or ""),
                heating_degree_days=processed.get("heating_degree_days"),
                seasonal_efficiency=processed.get("seasonal_efficiency"),
                refill_detected=processed.get("refill_detected"),
                leak_detected=processed.get("leak_detected"),
                raw_flags=str(processed.get("raw_flags"))
                if processed.get("raw_flags") is not None
                else None,
                litres_to_order=processed.get("litres_to_order"),
                bars_remaining=processed.get("bars_remaining"),
            )
        )
        await session.commit()


async def handle_payload(
    raw: dict[str, Any],
    *,
    sf: async_sessionmaker,
    settings_service,
    publisher: MqttPublisher,
    pubsub: PubSubBus,
    ctx_override: RecalcContext | None = None,
) -> dict[str, Any]:
    """Process one inbound Watchman Sonic JSON and fan out the result.

    Exposed at module level so unit tests can call it without spinning up an
    aiomqtt client. Returns the processed payload for assertion.
    """
    payload = _normalise_payload(raw)
    if payload.get("model") not in {"Oil-SonicSmart", "Oil-SonicAdv"}:
        logger.debug("Ignoring non-Watchman payload: %s", payload.get("model"))
        return {}
    ctx = ctx_override or await context_from_settings(settings_service)
    previous = await _load_previous(sf)
    processed = process(payload, ctx, previous=previous)
    await _persist_reading(sf, processed)
    await publisher.publish_level(processed)
    await pubsub.publish("reading", processed)
    return processed


class MqttIngest:
    """Lifespan-task wrapper.

    Phase 3 ships the orchestration shell. Phase 4 + 5 wire it into FastAPI's
    lifespan once the analysis / scheduler / publisher pieces are in place.
    The actual aiomqtt connect/loop is intentionally kept thin: most of the
    hard logic is in `handle_payload` so it's directly testable.
    """

    def __init__(
        self,
        *,
        sf: async_sessionmaker,
        settings_service,
        publisher: MqttPublisher,
        pubsub: PubSubBus,
    ) -> None:
        self._sf = sf
        self._settings = settings_service
        self._publisher = publisher
        self._pubsub = pubsub
        self._stop = asyncio.Event()
        self.connected = False

    def stop(self) -> None:
        self._stop.set()

    async def reconnect(self, key: str, old: Any, new: Any) -> None:
        # Settings change for mqtt.* — drop the loop so the outer task
        # reconnects with the fresh credentials. Phase 4/5 wires this in.
        logger.info("MQTT setting %s changed, scheduling reconnect", key)
        self.connected = False
        self._stop.set()
        # Caller responsible for restart — see lifespan integration in Phase 4/5.

    async def handle(self, raw: dict[str, Any]) -> dict[str, Any]:
        return await handle_payload(
            raw,
            sf=self._sf,
            settings_service=self._settings,
            publisher=self._publisher,
            pubsub=self._pubsub,
        )
