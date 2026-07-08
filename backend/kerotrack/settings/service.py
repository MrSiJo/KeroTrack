"""Settings service — typed get/set with audit log and change subscribers.

Coerces values per the catalogue's `value_type`, validates cron expressions,
maintains an in-process cache invalidated on `set`, and fires registered
change callbacks for glob patterns like `mqtt.*`.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
from collections.abc import Awaitable, Callable
from typing import Any

from cron_converter import Cron
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kerotrack.models.base import utc_now_iso
from kerotrack.models.setting import Setting
from kerotrack.models.setting_change import SettingChange
from kerotrack.settings.schema import (
    SETTINGS_CATALOGUE,
    SettingDef,
    get_setting_def,
)
from kerotrack.settings.url_guard import validate_url_setting


REDACTED_PUBLIC = "********"
REDACTED_AUDIT = "***"


class SettingError(ValueError):
    """Raised when a settings operation cannot be performed.

    Carries a short machine-readable code and an optional field-level reason
    so the API layer can surface 4xx responses cleanly.
    """

    def __init__(self, code: str, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


Subscriber = Callable[[str, Any, Any], Awaitable[None] | None]


class SettingsService:
    """Async service over the `settings` table.

    Construct with the session factory built in `db.session_factory(engine)`.
    The service is safe to keep on `app.state` for the lifetime of the process.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory
        self._cache: dict[str, Any] = {}
        self._subscribers: list[tuple[str, Subscriber]] = []
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ get

    async def get(self, key: str) -> Any:
        if key in self._cache:
            return self._cache[key]
        definition = get_setting_def(key)
        async with self._sf() as session:
            row = (
                await session.execute(select(Setting).where(Setting.key == key))
            ).scalar_one_or_none()
        if row is None:
            value = definition.default
        else:
            value = _decode_value(definition, row.value)
        # Re-check under the same lock `set()` holds: a `set` that committed
        # while our (pre-commit) read was in flight has already cached the
        # newer value — caching our stale read over it would stick until the
        # next set/invalidate (KERO-L3).
        async with self._lock:
            if key in self._cache:
                return self._cache[key]
            self._cache[key] = value
        return value

    async def all(self, group: str | None = None) -> list[dict[str, Any]]:
        async with self._sf() as session:
            stmt = select(Setting)
            if group is not None:
                stmt = stmt.where(Setting.group_name == group)
            rows = (await session.execute(stmt)).scalars().all()
        out: list[dict[str, Any]] = []
        for row in rows:
            definition = SETTINGS_CATALOGUE.get(row.key)
            if definition is None:
                # Stale key — surface so the operator can clean it up.
                out.append(
                    {
                        "key": row.key,
                        "value": None,
                        "value_type": row.value_type,
                        "group": row.group_name,
                        "label": row.label,
                        "description": row.description,
                        "is_secret": bool(row.is_secret),
                        "stale": True,
                    }
                )
                continue
            value: Any
            if definition.is_secret:
                value = REDACTED_PUBLIC
            else:
                value = _decode_value(definition, row.value)
            out.append(
                {
                    "key": row.key,
                    "value": value,
                    "value_type": definition.value_type,
                    "group": definition.group,
                    "label": definition.label,
                    "description": definition.description or None,
                    "is_secret": definition.is_secret,
                    "default": definition.default,
                }
            )
        out.sort(key=lambda r: (r["group"], r["key"]))
        return out

    # ------------------------------------------------------------------ set

    async def set(self, key: str, value: Any, *, source: str = "api") -> None:
        if key not in SETTINGS_CATALOGUE:
            raise SettingError("unknown_setting", f"Unknown setting: {key}", field=key)
        definition = SETTINGS_CATALOGUE[key]
        coerced = _coerce_value(definition, value)
        # SSRF guard: operator-set URLs the backend later fetches must pass
        # scheme/allowlist/internal-host checks before they hit the table.
        # Runs in a worker thread because the guard may do a blocking
        # getaddrinfo DNS lookup — a hanging resolver must not freeze the
        # event loop on a settings save (KERO-M1).
        await asyncio.to_thread(validate_url_setting, key, coerced)
        encoded = json.dumps(coerced)
        async with self._lock:
            async with self._sf() as session:
                old = (
                    await session.execute(select(Setting).where(Setting.key == key))
                ).scalar_one_or_none()
                old_value = (
                    _decode_value(definition, old.value) if old is not None else None
                )
                old_encoded = old.value if old is not None else None
                now = utc_now_iso()
                if old is None:
                    await session.execute(
                        insert(Setting).values(
                            key=key,
                            value=encoded,
                            value_type=definition.value_type,
                            group_name=definition.group,
                            label=definition.label,
                            description=definition.description or None,
                            is_secret=1 if definition.is_secret else 0,
                            updated_at=now,
                        )
                    )
                else:
                    await session.execute(
                        update(Setting)
                        .where(Setting.key == key)
                        .values(value=encoded, updated_at=now)
                    )
                await session.execute(
                    insert(SettingChange).values(
                        key=key,
                        old_value=_redact_for_audit(definition, old_encoded),
                        new_value=_redact_for_audit(definition, encoded),
                        changed_at=now,
                        source=source,
                    )
                )
                await session.commit()
            self._cache[key] = coerced
        await self._fire_subscribers(key, old_value, coerced)

    async def reset(self, key: str, *, source: str = "api") -> None:
        definition = get_setting_def(key)
        await self.set(key, definition.default, source=source)

    # ------------------------------------------------------------- audit log

    async def changes(
        self, *, key: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        async with self._sf() as session:
            stmt = select(SettingChange).order_by(SettingChange.id.desc()).limit(limit)
            if key:
                stmt = stmt.where(SettingChange.key == key)
            rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "id": row.id,
                "key": row.key,
                "old_value": row.old_value,
                "new_value": row.new_value,
                "changed_at": row.changed_at,
                "source": row.source,
            }
            for row in rows
        ]

    # ------------------------------------------------------------ subscribe

    def on_change(self, pattern: str, callback: Subscriber) -> None:
        self._subscribers.append((pattern, callback))

    async def _fire_subscribers(self, key: str, old: Any, new: Any) -> None:
        for pattern, callback in self._subscribers:
            if not fnmatch.fnmatchcase(key, pattern):
                continue
            result = callback(key, old, new)
            if asyncio.iscoroutine(result):
                await result

    # ----------------------------------------------------------------- cache

    def invalidate_cache(self) -> None:
        self._cache.clear()


# ---------------------------------------------------------------- coercion

def _coerce_value(definition: SettingDef, raw: Any) -> Any:
    vt = definition.value_type
    if vt == "string":
        if raw is None:
            return ""
        return str(raw)
    if vt == "secret":
        if raw is None:
            return ""
        return str(raw)
    if vt == "int":
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise SettingError(
                "invalid_int",
                f"{definition.key}: expected int, got {raw!r}",
                field=definition.key,
            ) from exc
    if vt == "float":
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise SettingError(
                "invalid_float",
                f"{definition.key}: expected float, got {raw!r}",
                field=definition.key,
            ) from exc
        if definition.min_value is not None and value < definition.min_value:
            raise SettingError(
                "out_of_range",
                f"{definition.key}: must be >= {definition.min_value}",
                field=definition.key,
            )
        if definition.max_value is not None and value > definition.max_value:
            raise SettingError(
                "out_of_range",
                f"{definition.key}: must be <= {definition.max_value}",
                field=definition.key,
            )
        return value
    if vt == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        if isinstance(raw, str):
            v = raw.strip().lower()
            if v in {"true", "1", "yes", "on"}:
                return True
            if v in {"false", "0", "no", "off", ""}:
                return False
        raise SettingError(
            "invalid_bool",
            f"{definition.key}: expected bool, got {raw!r}",
            field=definition.key,
        )
    if vt == "cron":
        if not isinstance(raw, str) or not raw.strip():
            raise SettingError(
                "invalid_cron",
                f"{definition.key}: expected cron string",
                field=definition.key,
            )
        try:
            Cron(raw.strip())
        except Exception as exc:
            raise SettingError(
                "invalid_cron",
                f"{definition.key}: invalid cron expression — {exc}",
                field=definition.key,
            ) from exc
        return raw.strip()
    if vt == "json":
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SettingError(
                    "invalid_json",
                    f"{definition.key}: invalid JSON — {exc}",
                    field=definition.key,
                ) from exc
        else:
            value = raw
        return value
    raise SettingError(
        "unknown_type",
        f"{definition.key}: unknown value_type {vt!r}",
        field=definition.key,
    )


def _decode_value(definition: SettingDef, encoded: str) -> Any:
    try:
        return json.loads(encoded)
    except json.JSONDecodeError:
        # Tolerate legacy plain strings stored without JSON quoting.
        return encoded


def _redact_for_audit(definition: SettingDef, encoded: str | None) -> str | None:
    if encoded is None:
        return None
    return REDACTED_AUDIT if definition.is_secret else encoded
