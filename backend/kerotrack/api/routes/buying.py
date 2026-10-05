"""Buy planner routes: summary, quote history, manual run, calibration preview."""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from kerotrack.analysis.hot_water import hw_litres_per_day_avg
from kerotrack.buying.service import build_summary
from kerotrack.clock import local_now
from kerotrack.models.price_quote import PriceQuote
from kerotrack.projection.service import load_hw, run_calibration
from kerotrack.quotes.store import history

router = APIRouter(prefix="/api/buying", tags=["buying"])


def _to_dict(row: PriceQuote) -> dict[str, Any]:
    cols = row.__table__.columns.keys()
    return {c: getattr(row, c) for c in cols}


@router.get("/summary")
async def summary(request: Request) -> dict[str, Any]:
    return await build_summary(
        request.app.state.session_factory,
        request.app.state.settings_service,
        now=local_now(),
    )


@router.get("/quotes")
async def quotes(
    request: Request,
    days: int = Query(default=90, ge=1, le=730),
) -> dict[str, Any]:
    rows = await history(
        request.app.state.session_factory,
        since=local_now() - timedelta(days=days),
    )
    return {"items": [_to_dict(r) for r in rows]}


@router.post("/run")
async def run(request: Request) -> Any:
    """Run the buying job now (every configured provider) and return its summary.

    Writes no settings.
    """
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="scheduler_not_running")
    return await scheduler.trigger_now("buying_all")


@router.post("/calibrate")
async def calibrate(request: Request) -> dict[str, Any]:
    """Preview a calibration fit. Writes no settings."""
    sf = request.app.state.session_factory
    svc = request.app.state.settings_service
    cal = await run_calibration(sf, svc, now=local_now())
    schedule, minutes, rate = await load_hw(svc)
    out = dataclasses.asdict(cal)
    out["current_burner_minutes"] = round(float(minutes), 2)
    out["current_hw_l_per_day"] = round(
        hw_litres_per_day_avg(schedule, minutes, rate), 2
    )
    return out
