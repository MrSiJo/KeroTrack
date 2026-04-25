"""Health endpoint per spec §6.7."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from sqlalchemy import desc, select, text

from kerotrack.models.reading import Reading

router = APIRouter(tags=["health"])


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    candidates = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S.%f",
    )
    for fmt in candidates:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        return None


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
            ts = _parse_iso(row)
            if ts is not None:
                age = (datetime.now(UTC) - ts).total_seconds()
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
