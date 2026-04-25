"""Settings API routes per spec §5.5."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from kerotrack.api.deps import get_settings_service
from kerotrack.settings.schema import SETTINGS_CATALOGUE, get_setting_def
from kerotrack.settings.service import (
    REDACTED_PUBLIC,
    SettingError,
    SettingsService,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SetValueBody(BaseModel):
    value: Any


@router.get("")
async def list_settings(
    group: str | None = Query(default=None),
    svc: SettingsService = Depends(get_settings_service),
) -> dict[str, Any]:
    rows = await svc.all(group=group)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["group"], []).append(row)
    return {"groups": grouped, "items": rows}


@router.get("/schema")
async def get_schema() -> dict[str, Any]:
    catalogue = []
    for definition in SETTINGS_CATALOGUE.values():
        catalogue.append(
            {
                "key": definition.key,
                "value_type": definition.value_type,
                "group": definition.group,
                "label": definition.label,
                "description": definition.description or None,
                "default": "********"
                if definition.is_secret
                else definition.default,
                "is_secret": definition.is_secret,
                "requires_restart": definition.requires_restart,
                "min_value": definition.min_value,
                "max_value": definition.max_value,
                "step": definition.step,
            }
        )
    catalogue.sort(key=lambda d: (d["group"], d["key"]))
    return {"catalogue": catalogue}


@router.get("/changes")
async def list_changes(
    key: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    svc: SettingsService = Depends(get_settings_service),
) -> dict[str, Any]:
    return {"changes": await svc.changes(key=key, limit=limit)}


@router.get("/{key}")
async def get_setting(
    key: str,
    svc: SettingsService = Depends(get_settings_service),
) -> dict[str, Any]:
    if key not in SETTINGS_CATALOGUE:
        raise SettingError(
            "unknown_setting", f"Unknown setting: {key}", field=key
        )
    definition = SETTINGS_CATALOGUE[key]
    if definition.is_secret:
        value: Any = REDACTED_PUBLIC
    else:
        value = await svc.get(key)
    return {
        "key": key,
        "value": value,
        "value_type": definition.value_type,
        "group": definition.group,
        "is_secret": definition.is_secret,
    }


@router.put("/{key}")
async def put_setting(
    key: str,
    body: SetValueBody,
    svc: SettingsService = Depends(get_settings_service),
) -> dict[str, Any]:
    await svc.set(key, body.value, source="api")
    definition = get_setting_def(key)
    if definition.is_secret:
        value: Any = REDACTED_PUBLIC
    else:
        value = await svc.get(key)
    return {"key": key, "value": value}


@router.put("")
async def bulk_put_settings(
    body: dict[str, Any],
    svc: SettingsService = Depends(get_settings_service),
) -> dict[str, Any]:
    if not isinstance(body, dict) or not body:
        raise HTTPException(status_code=400, detail="empty_body")
    saved: list[str] = []
    errors: list[dict[str, Any]] = []
    for key, value in body.items():
        try:
            await svc.set(key, value, source="api")
        except SettingError as exc:
            errors.append({"key": key, "code": exc.code, "message": str(exc)})
            continue
        saved.append(key)
    if errors:
        return {"saved": saved, "errors": errors}
    return {"saved": saved}


@router.post("/{key}/reset")
async def reset_setting(
    key: str,
    svc: SettingsService = Depends(get_settings_service),
) -> dict[str, Any]:
    await svc.reset(key, source="api")
    definition = get_setting_def(key)
    if definition.is_secret:
        value: Any = REDACTED_PUBLIC
    else:
        value = await svc.get(key)
    return {"key": key, "value": value}
