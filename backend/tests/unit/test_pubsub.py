"""Pubsub bus delivery and isolation."""

from __future__ import annotations

import asyncio

import pytest

from kerotrack.pubsub.bus import PubSubBus


pytestmark = pytest.mark.asyncio


async def test_publish_delivers_to_all_subscribers() -> None:
    bus = PubSubBus()
    a = bus.subscribe("reading")
    b = bus.subscribe("reading")
    await bus.publish("reading", {"id": 1})
    assert (await a.get())[1] == {"id": 1}
    assert (await b.get())[1] == {"id": 1}


async def test_publish_isolates_channels() -> None:
    bus = PubSubBus()
    reading_q = bus.subscribe("reading")
    analysis_q = bus.subscribe("analysis")
    await bus.publish("reading", {"x": 1})
    assert reading_q.qsize() == 1
    assert analysis_q.qsize() == 0


async def test_publish_drops_when_subscriber_full() -> None:
    bus = PubSubBus(queue_size=1)
    q = bus.subscribe("reading")
    await bus.publish("reading", "first")
    await bus.publish("reading", "second")  # dropped silently
    assert q.qsize() == 1
    msg = await q.get()
    assert msg == ("reading", "first")


async def test_unsubscribe_stops_further_delivery() -> None:
    bus = PubSubBus()
    q = bus.subscribe("reading")
    bus.unsubscribe("reading", q)
    await bus.publish("reading", "x")
    assert q.qsize() == 0
