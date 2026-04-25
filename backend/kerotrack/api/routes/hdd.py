"""HDD data list."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import desc, select

from kerotrack.models.hdd import HddDatum

router = APIRouter(prefix="/api/hdd", tags=["hdd"])


@router.get("")
async def list_hdd(
    request: Request,
    limit: int = Query(default=24, ge=1, le=120),
) -> dict[str, list[dict[str, object]]]:
    sf = request.app.state.session_factory
    async with sf() as session:
        rows = (
            await session.execute(
                select(HddDatum).order_by(desc(HddDatum.date)).limit(limit)
            )
        ).scalars().all()
    return {"items": [{"date": r.date, "hdd": r.hdd} for r in rows]}
