"""Health endpoint per spec §6.7."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import desc, select, text

from kerotrack.clock import local_now, parse_local
from kerotrack.models.reading import Reading

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health(request: Request) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "ok",
        "db": "unknown",
        "mqtt_connected": False,
        "last_reading_at": None,
        "age_seconds": None,
        "scheduler_running": False,
    }

    sf = getattr(request.app.state, "session_factory", None)
    if sf is None:
        payload["db"] = "down"
        payload["status"] = "degraded"
        return payload

    try:
        async with sf() as session:
            await session.execute(text("SELECT 1"))
            row = (
                await session.execute(
                    select(Reading.date)
                    .order_by(desc(Reading.date))
                    .limit(1)
                )
            ).scalar_one_or_none()
        payload["db"] = "ok"
        if row is not None:
            payload["last_reading_at"] = row
            ts = parse_local(row)
            if ts is not None:
                age = (local_now() - ts).total_seconds()
                payload["age_seconds"] = max(int(age), 0)
    except Exception:
        payload["db"] = "down"
        payload["status"] = "degraded"

    mqtt = getattr(request.app.state, "mqtt", None)
    if mqtt is not None:
        payload["mqtt_connected"] = bool(getattr(mqtt, "connected", False))

    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        payload["scheduler_running"] = bool(getattr(scheduler, "running", False))

    return payload
