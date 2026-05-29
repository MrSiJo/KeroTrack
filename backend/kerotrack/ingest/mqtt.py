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

import aiomqtt
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.ingest.raw_capture import persist_raw_capture
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


async def _load_previous(
    sf: async_sessionmaker, *, before_date: str | None = None
) -> PreviousReading | None:
    """Fetch the most recent TRUSTED reading strictly before `before_date`.

    Trusted = not stamped with the `noise_suppressed` sentinel in
    `raw_flags`. Chaining through noisy rows is what stops the Watchman
    Sonic's "stuck-at-wrong-reflection" chain from leaking past the
    sanity bound: when the sensor reports 80 → 100 → 100 → 100 → 80,
    every 100-cm reading compares against the trusted 80 cm baseline
    instead of the immediately previous (also-noisy) 100 cm row, so the
    whole chain gets marked.

    When ingest first lands a brand-new payload, `before_date` is the
    new payload's timestamp; without this filter we would compare
    against rows AT or AFTER that timestamp (e.g. duplicate upserts, or
    already-migrated rows that share the same minute). That collapses
    `litres_used_since_last` to 0 for every recurrence.
    """
    noise_clause = (Reading.raw_flags.is_(None)) | (
        ~Reading.raw_flags.like("%noise_suppressed%")
    )
    async with sf() as session:
        trusted_stmt = (
            select(Reading.date, Reading.litres_remaining, Reading.air_gap_cm)
            .where(noise_clause)
            .order_by(desc(Reading.date))
            .limit(1)
        )
        watchdog_stmt = (
            select(Reading.date).order_by(desc(Reading.date)).limit(1)
        )
        if before_date is not None:
            trusted_stmt = (
                select(Reading.date, Reading.litres_remaining, Reading.air_gap_cm)
                .where(Reading.date < before_date, noise_clause)
                .order_by(desc(Reading.date))
                .limit(1)
            )
            watchdog_stmt = (
                select(Reading.date)
                .where(Reading.date < before_date)
                .order_by(desc(Reading.date))
                .limit(1)
            )
        row = (await session.execute(trusted_stmt)).first()
        watchdog_row = (await session.execute(watchdog_stmt)).first()
    if row is None or row.litres_remaining is None or row.air_gap_cm is None:
        return None
    try:
        ts = datetime.strptime(row.date, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    watchdog_ts: datetime | None = None
    if watchdog_row is not None and watchdog_row.date != row.date:
        try:
            watchdog_ts = datetime.strptime(
                watchdog_row.date, "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            watchdog_ts = None
    return PreviousReading(
        date=ts,
        litres_remaining=float(row.litres_remaining),
        air_gap_cm=float(row.air_gap_cm),
        most_recent_date=watchdog_ts,
    )


def _normalise_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Massage the RTL_433 payload into the shape `recalc.process` expects."""
    from kerotrack.clock import local_now_str

    payload = dict(raw)
    if payload.get("model") == "Oil-SonicAdv":
        payload["model"] = "Oil-SonicSmart"
    if "time" not in payload:
        # Local time matches v1 — DST handled via bootstrap.tz.
        payload["time"] = local_now_str()
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
    price_provider=None,
    topic: str | None = None,
) -> dict[str, Any]:
    """Process one inbound Watchman Sonic JSON and fan out the result.

    `price_provider` is an awaitable returning the current pence-per-litre
    (cached, with stale-fallback). Tests pass None and rely on
    `ctx_override`. `topic` is the source MQTT topic, recorded with the raw
    capture.
    """
    payload = _normalise_payload(raw)
    if payload.get("model") not in {"Oil-SonicSmart", "Oil-SonicAdv"}:
        logger.debug("Ignoring non-Watchman payload: %s", payload.get("model"))
        return {}
    if ctx_override is not None:
        ctx = ctx_override
    else:
        ppl: float | None = None
        if price_provider is not None:
            try:
                ppl = await price_provider()
            except Exception:  # noqa: BLE001
                logger.warning("price_provider failed", exc_info=True)
        ctx = await context_from_settings(settings_service, current_ppl=ppl)

    new_date = datetime.strptime(payload["time"], "%Y-%m-%d %H:%M:%S").strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    previous = await _load_previous(sf, before_date=new_date)
    processed = process(payload, ctx, previous=previous)
    await _persist_reading(sf, processed)
    # Archive the verbatim payload alongside the reading. Best-effort: a
    # capture failure must never lose the reading or block the publish.
    try:
        await persist_raw_capture(
            sf, raw, topic=topic, sensor_time=processed["date"]
        )
    except Exception:  # noqa: BLE001
        logger.warning("raw capture failed", exc_info=True)
    await publisher.publish_level(processed)
    await pubsub.publish("reading", processed)
    return processed


class _AiomqttPublisherAdapter:
    """Adapt an aiomqtt.Client to the duck-typed MqttPublisher interface."""

    def __init__(self) -> None:
        self._client: aiomqtt.Client | None = None

    def bind(self, client: aiomqtt.Client | None) -> None:
        self._client = client

    async def publish(
        self, topic: str, payload: str | bytes, *, qos: int = 0, retain: bool = False
    ) -> Any:
        if self._client is None:
            logger.debug("publish dropped — no broker connected")
            return None
        try:
            await self._client.publish(topic, payload, qos=qos, retain=retain)
        except Exception as exc:  # noqa: BLE001
            logger.warning("publish failed: %s", exc)


class MqttIngest:
    """Live aiomqtt subscriber + publisher loop.

    The publisher adapter is created up-front so `app.state.publisher` can
    be wired into the lifespan synchronously; we bind the live client onto
    it once the connection succeeds. The subscriber loop reconnects on
    error with exponential backoff and survives settings changes via
    `reconnect()` (called by the SettingsService change subscriber).
    """

    def __init__(
        self,
        *,
        sf: async_sessionmaker,
        settings_service,
        pubsub: PubSubBus,
        feed_ring=None,
        price_provider=None,
    ) -> None:
        self._sf = sf
        self._settings = settings_service
        self._pubsub = pubsub
        self._feed = feed_ring
        self._price_provider = price_provider
        self._stop = asyncio.Event()
        self._reload = asyncio.Event()
        self.connected = False
        self._adapter = _AiomqttPublisherAdapter()
        self.publisher = self._build_publisher()

    def _build_publisher(self) -> MqttPublisher:
        # Topic strings come from settings at run time inside the loop, but
        # the publisher's defaults match the v1 contract. Lifespan refreshes
        # publish topics whenever they change.
        return MqttPublisher(client=self._adapter)

    async def _refresh_publisher_topics(self) -> None:
        topic_level = str(await self._settings.get("mqtt.topic_readings_publish"))
        topic_analysis = str(await self._settings.get("mqtt.topic_analytics"))
        topic_costanalysis = str(await self._settings.get("mqtt.topic_costanalysis"))
        self.publisher = MqttPublisher(
            client=self._adapter,
            topic_level=topic_level,
            topic_analysis=topic_analysis,
            topic_costanalysis=topic_costanalysis,
        )

    def stop(self) -> None:
        self._stop.set()
        self._reload.set()

    async def reconnect(self, key: str, old: Any, new: Any) -> None:
        logger.info("MQTT setting %s changed → triggering reconnect", key)
        self._reload.set()

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            self._reload.clear()
            try:
                broker = str(await self._settings.get("mqtt.broker"))
                port = int(await self._settings.get("mqtt.port"))
                username = str(await self._settings.get("mqtt.username")) or None
                password = str(await self._settings.get("mqtt.password")) or None
                subscribe_topic = str(await self._settings.get("mqtt.topic_readings"))
            except Exception as exc:  # noqa: BLE001
                logger.exception("failed to load mqtt settings: %s", exc)
                await asyncio.sleep(5)
                continue

            if not broker or broker.lower() == "localhost":
                # Sit idle until the operator points at a real broker.
                logger.info("mqtt.broker=%r — ingest idle until reconfigured", broker)
                self.connected = False
                self._adapter.bind(None)
                try:
                    await asyncio.wait_for(self._reload.wait(), timeout=30)
                except asyncio.TimeoutError:
                    pass
                continue

            await self._refresh_publisher_topics()
            logger.info(
                "MQTT connecting to %s:%s as %s, subscribing %s",
                broker, port, username, subscribe_topic,
            )
            try:
                async with aiomqtt.Client(
                    hostname=broker,
                    port=port,
                    username=username,
                    password=password,
                    keepalive=60,
                ) as client:
                    self._adapter.bind(client)
                    self.connected = True
                    backoff = 1.0
                    await client.subscribe(subscribe_topic, qos=0)

                    consumer = asyncio.create_task(self._consume(client))
                    waiter = asyncio.create_task(self._reload.wait())
                    stopper = asyncio.create_task(self._stop.wait())
                    done, pending = await asyncio.wait(
                        {consumer, waiter, stopper},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()
                    for t in done:
                        if t is consumer and t.exception():
                            raise t.exception()  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001
                logger.warning("MQTT loop error: %s — backing off %.1fs", exc, backoff)
                self.connected = False
                self._adapter.bind(None)
                try:
                    await asyncio.wait_for(self._reload.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 60.0)
                continue
            finally:
                self.connected = False
                self._adapter.bind(None)

        logger.info("MQTT ingest loop stopped")

    async def _consume(self, client: aiomqtt.Client) -> None:
        async for msg in client.messages:
            try:
                body = msg.payload.decode() if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload)
                try:
                    raw = json.loads(body)
                except json.JSONDecodeError:
                    logger.debug("Non-JSON MQTT payload on %s: %r", msg.topic, body[:200])
                    continue

                if self._feed is not None:
                    self._feed.append(topic=str(msg.topic), payload=raw)

                # Only RTL_433 Watchman Sonic payloads carry the depth_cm/temperature_C
                # we expect. Skip anything else (e.g. our own publishes echoed back
                # if subscribed to a wildcard).
                if "depth_cm" not in raw or "temperature_C" not in raw:
                    continue

                await handle_payload(
                    raw,
                    sf=self._sf,
                    settings_service=self._settings,
                    publisher=self.publisher,
                    pubsub=self._pubsub,
                    price_provider=self._price_provider,
                    topic=str(msg.topic),
                )
            except Exception:  # noqa: BLE001
                logger.exception("error handling MQTT message")
