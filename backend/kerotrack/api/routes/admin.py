"""Admin endpoints — manual job triggers and settings reload."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from kerotrack.notifier.apprise_notifier import run as run_notifier
from kerotrack.scheduler.jobs import JOB_NAMES

router = APIRouter(prefix="/api/admin", tags=["admin"])


class JobRunBody(BaseModel):
    test: bool = False


@router.post("/jobs/{name}/run")
async def run_job(name: str, body: JobRunBody, request: Request) -> dict[str, Any]:
    if name not in JOB_NAMES:
        raise HTTPException(status_code=404, detail="unknown_job")

    state = request.app.state
    if name == "notifier":
        result = await run_notifier(
            sf=state.session_factory,
            settings_service=state.settings_service,
            test_mode=body.test,
        )
        return {
            "sent": result.sent,
            "channels": result.channels,
            "title": result.title,
            "skipped_reason": result.skipped_reason,
        }

    scheduler = getattr(state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="scheduler_not_running")
    out = await scheduler.trigger_now(name)
    return {"ok": True, "result": out}


@router.post("/reload-settings")
async def reload_settings(request: Request) -> dict[str, Any]:
    svc = request.app.state.settings_service
    svc.invalidate_cache()
    return {"ok": True}
