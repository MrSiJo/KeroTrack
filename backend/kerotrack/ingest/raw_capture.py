"""Raw MQTT capture — persist verbatim inbound payloads and prune them.

`persist_raw_capture` runs alongside recalc in `ingest/mqtt.py` so every
processed reading also archives its raw payload (rssi/status included).
`prune_raw_captures` backs the `kerotrack prune-raw` break-glass command.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.models.raw_capture import RawCapture


def _coerce(raw: dict[str, Any], key: str, cast):
    """Pull `key` from the payload and cast it, tolerating absence/garbage."""
    val = raw.get(key)
    if val is None:
        return None
    try:
        return cast(val)
    except (TypeError, ValueError):
        return None


async def persist_raw_capture(
    sf: async_sessionmaker,
    raw: dict[str, Any],
    *,
    topic: str | None,
    sensor_time: str | None,
) -> None:
    """Archive one verbatim inbound payload.

    Uses its own session so a capture failure can't roll back an
    already-committed reading. The caller still guards the call, so an
    error here never reaches the live ingest path.
    """
    from kerotrack.clock import local_now_str

    async with sf() as session:
        session.add(
            RawCapture(
                received_at=local_now_str(),
                topic=topic,
                sensor_time=sensor_time,
                rssi=_coerce(raw, "rssi", int),
                status=_coerce(raw, "status", int),
                depth_cm=_coerce(raw, "depth_cm", float),
                temperature_c=_coerce(raw, "temperature_C", float),
                raw_json=json.dumps(raw, default=str, sort_keys=True),
            )
        )
        await session.commit()


async def prune_raw_captures(
    sf: async_sessionmaker, *, before: str, apply: bool = False
) -> dict[str, Any]:
    """Delete raw_captures with ``received_at`` lexically before ``before``.

    ``before`` is a ``YYYY-MM-DD`` string; ``received_at`` is
    ``YYYY-MM-DD HH:MM:SS`` so a plain string comparison is a correct date
    cutoff (a row exactly on the cutoff date is kept). Dry-run by default —
    pass ``apply=True`` to delete.
    """
    async with sf() as session:
        total = (
            await session.execute(select(func.count()).select_from(RawCapture))
        ).scalar_one()
        matched = (
            await session.execute(
                select(func.count())
                .select_from(RawCapture)
                .where(RawCapture.received_at < before)
            )
        ).scalar_one()
        if apply and matched:
            await session.execute(
                delete(RawCapture).where(RawCapture.received_at < before)
            )
            await session.commit()
    return {
        "apply": apply,
        "before": before,
        "total": total,
        "matched": matched,
        "deleted": matched if apply else 0,
    }
