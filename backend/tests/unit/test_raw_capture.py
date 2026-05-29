"""Raw MQTT capture — verbatim payload archive + manual prune.

The capture runs alongside recalc in ingest so the rssi/status history the
`readings` table discards is reviewable after the fact (OpenMQTTGateway
publishes without retain, so the broker keeps no history).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.ingest.raw_capture import persist_raw_capture, prune_raw_captures
from kerotrack.models.raw_capture import RawCapture


pytestmark = pytest.mark.asyncio


async def test_persist_extracts_diagnostic_fields(sf: async_sessionmaker) -> None:
    raw = {
        "time": "2026-05-29 09:10:15",
        "model": "Oil-SonicAdv",
        "id": 12345,
        "depth_cm": 93.0,
        "temperature_C": 14.0,
        "rssi": -58,
        "status": 144,
    }
    await persist_raw_capture(
        sf, raw, topic="home/OMG/433/Oil", sensor_time="2026-05-29 09:10:15"
    )

    async with sf() as session:
        rows = (await session.execute(select(RawCapture))).scalars().all()
    assert len(rows) == 1
    r = rows[0]
    assert r.topic == "home/OMG/433/Oil"
    assert r.sensor_time == "2026-05-29 09:10:15"
    assert r.rssi == -58
    assert r.status == 144
    assert r.depth_cm == 93.0
    assert r.temperature_c == 14.0
    assert r.received_at  # stamped with our wall-clock
    # raw_json round-trips the verbatim payload.
    assert json.loads(r.raw_json)["id"] == 12345


async def test_persist_tolerates_missing_rssi(sf: async_sessionmaker) -> None:
    raw = {
        "time": "2026-05-29 09:40:15",
        "model": "Oil-SonicAdv",
        "id": 12345,
        "depth_cm": 80.0,
        "temperature_C": 15.0,
        "status": 144,
    }
    await persist_raw_capture(sf, raw, topic="t", sensor_time="2026-05-29 09:40:15")

    async with sf() as session:
        r = (await session.execute(select(RawCapture))).scalars().one()
    assert r.rssi is None
    assert r.depth_cm == 80.0
    assert json.loads(r.raw_json)["status"] == 144


async def _seed_three(sf: async_sessionmaker) -> None:
    async with sf() as session:
        for ts in ["2025-01-01 12:00:00", "2025-06-01 12:00:00", "2026-01-01 12:00:00"]:
            session.add(RawCapture(received_at=ts, topic="t", raw_json="{}"))
        await session.commit()


async def test_prune_dry_run_reports_without_deleting(sf: async_sessionmaker) -> None:
    await _seed_three(sf)
    report = await prune_raw_captures(sf, before="2025-12-31", apply=False)
    assert report["total"] == 3
    assert report["matched"] == 2
    assert report["deleted"] == 0
    async with sf() as session:
        assert len((await session.execute(select(RawCapture))).scalars().all()) == 3


async def test_prune_apply_deletes_old_rows(sf: async_sessionmaker) -> None:
    await _seed_three(sf)
    report = await prune_raw_captures(sf, before="2025-12-31", apply=True)
    assert report["matched"] == 2
    assert report["deleted"] == 2
    async with sf() as session:
        rows = (await session.execute(select(RawCapture))).scalars().all()
    assert len(rows) == 1
    assert rows[0].received_at == "2026-01-01 12:00:00"
