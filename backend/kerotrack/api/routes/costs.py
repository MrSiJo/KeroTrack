"""Cost analysis + refill periods routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import desc, select

from kerotrack.models.cost_analysis import CostAnalysis
from kerotrack.models.refill_period import RefillPeriod

router = APIRouter(prefix="/api/costs", tags=["costs"])


def _to_dict(row: Any) -> dict[str, Any]:
    cols = row.__table__.columns.keys()
    return {c: getattr(row, c) for c in cols}


@router.get("/summary")
async def summary(request: Request) -> dict[str, Any]:
    sf = request.app.state.session_factory
    async with sf() as session:
        latest = (
            await session.execute(
                select(CostAnalysis)
                .order_by(desc(CostAnalysis.analysis_date))
                .limit(1)
            )
        ).scalar_one_or_none()
    if latest is None:
        raise HTTPException(status_code=404, detail="no_cost_analysis_yet")
    return _to_dict(latest)


@router.get("/periods")
async def list_periods(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    sf = request.app.state.session_factory
    async with sf() as session:
        rows = (
            await session.execute(
                select(RefillPeriod)
                .order_by(desc(RefillPeriod.end_date))
                .limit(limit)
            )
        ).scalars().all()
    return {"items": [_to_dict(r) for r in rows]}
