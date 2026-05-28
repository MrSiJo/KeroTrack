"""GET /api/status — top-level snapshot for the Dashboard."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import desc, select

from kerotrack.models.analysis_result import AnalysisResult
from kerotrack.models.cost_analysis import CostAnalysis
from kerotrack.models.reading import Reading

router = APIRouter(prefix="/api/status", tags=["status"])


@router.get("")
async def get_status(request: Request) -> dict[str, Any]:
    sf = request.app.state.session_factory
    async with sf() as session:
        # Dashboard gauge reads `reading.percentage_remaining` / litres
        # directly, so the latest TRUSTED row is what we want — a
        # noise-suppressed row's bad litres value would otherwise show
        # up as the current tank level.
        latest_reading = (
            await session.execute(
                select(Reading)
                .where(
                    (Reading.raw_flags.is_(None))
                    | (~Reading.raw_flags.like("%noise_suppressed%"))
                )
                .order_by(desc(Reading.date))
                .limit(1)
            )
        ).scalar_one_or_none()
        # Order by when the analysis was COMPUTED, not by which reading
        # it covers — once we started skipping noise_suppressed rows for
        # the "latest reading", a freshly-computed analysis row can have
        # a slightly older `latest_reading_date` than a stale row that
        # was based on a noisy reading. The most recently computed view
        # is always the one we want.
        latest_analysis = (
            await session.execute(
                select(AnalysisResult)
                .order_by(desc(AnalysisResult.latest_analysis_date))
                .limit(1)
            )
        ).scalar_one_or_none()
        latest_cost = (
            await session.execute(
                select(CostAnalysis)
                .order_by(desc(CostAnalysis.analysis_date))
                .limit(1)
            )
        ).scalar_one_or_none()

    def _row_to_dict(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        cols = row.__table__.columns.keys()
        return {c: getattr(row, c) for c in cols}

    return {
        "reading": _row_to_dict(latest_reading),
        "analysis": _row_to_dict(latest_analysis),
        "cost": _row_to_dict(latest_cost),
    }
