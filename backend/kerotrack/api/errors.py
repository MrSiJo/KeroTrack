"""Centralised exception → HTTP error mapping."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kerotrack.settings.service import SettingError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SettingError)
    async def _handle_setting_error(_: Request, exc: SettingError) -> JSONResponse:  # type: ignore[unused-ignore]
        if exc.code == "unknown_setting":
            status = 400
        elif exc.code in {
            "invalid_int",
            "invalid_float",
            "invalid_bool",
            "invalid_cron",
            "invalid_json",
            "out_of_range",
            "unknown_type",
        }:
            status = 422
        else:
            status = 400
        return JSONResponse(
            status_code=status,
            content={
                "error": exc.code,
                "message": str(exc),
                "field": exc.field,
            },
        )
