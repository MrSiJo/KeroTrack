"""Common FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from kerotrack.settings.service import SettingsService


def get_settings_service(request: Request) -> SettingsService:
    svc = getattr(request.app.state, "settings_service", None)
    if svc is None:
        raise RuntimeError("SettingsService not initialised on app.state")
    return svc
