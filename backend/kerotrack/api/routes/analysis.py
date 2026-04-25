"""Analysis history routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import desc, select

from kerotrack.models.analysis_result import AnalysisResult

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _to_dict(row: AnalysisResult) -> dict[str, Any]:
    cols = row.__table__.columns.keys()
    return {c: getattr(row, c) for c in cols}


@router.get("/latest")
async def latest(request: Request) -> dict[str, Any]:
    sf = request.app.state.session_factory
    async with sf() as session:
        row = (
            await session.execute(
                select(AnalysisResult)
                .order_by(desc(AnalysisResult.latest_reading_date))
                .limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="no_analysis_yet")
    return _to_dict(row)


@router.get("/history")
async def history(
    request: Request,
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict[str, Any]:
    sf = request.app.state.session_factory
    async with sf() as session:
        rows = (
            await session.execute(
                select(AnalysisResult)
                .order_by(desc(AnalysisResult.latest_reading_date))
                .limit(limit)
            )
        ).scalars().all()
    return {"items": [_to_dict(r) for r in rows]}
