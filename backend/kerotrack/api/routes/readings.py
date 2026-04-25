"""Readings CRUD."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import asc, desc, delete, func, select, update

from kerotrack.models.reading import Reading

router = APIRouter(prefix="/api/readings", tags=["readings"])


class ReadingPatch(BaseModel):
    temperature: float | None = None
    litres_remaining: float | None = None
    litres_used_since_last: float | None = None
    percentage_remaining: float | None = None
    oil_depth_cm: float | None = None
    air_gap_cm: float | None = None
    current_ppl: float | None = None
    cost_used: str | None = None
    cost_to_fill: str | None = None
    refill_detected: str | None = None
    leak_detected: str | None = None


def _to_dict(row: Reading) -> dict[str, Any]:
    cols = row.__table__.columns.keys()
    return {c: getattr(row, c) for c in cols}


@router.get("")
async def list_readings(
    request: Request,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
) -> dict[str, Any]:
    sf = request.app.state.session_factory
    direction = desc if order == "desc" else asc
    async with sf() as session:
        stmt = select(Reading)
        if since:
            stmt = stmt.where(Reading.date >= since)
        if until:
            stmt = stmt.where(Reading.date <= until)
        total = (
            await session.execute(
                select(func.count()).select_from(stmt.subquery())
            )
        ).scalar_one()
        rows = (
            await session.execute(
                stmt.order_by(direction(Reading.date)).limit(limit).offset(offset)
            )
        ).scalars().all()
    return {
        "total": int(total),
        "items": [_to_dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get("/{date_id}")
async def get_reading(date_id: str, request: Request) -> dict[str, Any]:
    # `date_id` is "<date> <time>" with a space; FastAPI URL-decodes it.
    sf = request.app.state.session_factory
    async with sf() as session:
        row = (
            await session.execute(
                select(Reading).where(Reading.date == date_id)
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    return _to_dict(row)


@router.patch("/{date_id}")
async def patch_reading(
    date_id: str, body: ReadingPatch, request: Request
) -> dict[str, Any]:
    sf = request.app.state.session_factory
    diff = body.model_dump(exclude_unset=True)
    if not diff:
        raise HTTPException(status_code=400, detail="empty_patch")
    async with sf() as session:
        result = await session.execute(
            update(Reading).where(Reading.date == date_id).values(**diff)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="not_found")
        row = (
            await session.execute(
                select(Reading).where(Reading.date == date_id)
            )
        ).scalar_one()
        await session.commit()
    return _to_dict(row)


@router.delete("/{date_id}")
async def delete_reading(date_id: str, request: Request) -> dict[str, Any]:
    sf = request.app.state.session_factory
    async with sf() as session:
        result = await session.execute(delete(Reading).where(Reading.date == date_id))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="not_found")
        await session.commit()
    return {"ok": True}
