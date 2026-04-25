"""Idempotent seed of the settings catalogue defaults.

Inserts a row for every key in `SETTINGS_CATALOGUE` that doesn't already
exist. Never overwrites operator changes.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from kerotrack.models.base import utc_now_iso
from kerotrack.models.setting import Setting
from kerotrack.models.setting_change import SettingChange
from kerotrack.settings.schema import SETTINGS_CATALOGUE, SettingDef


def _encode_default(definition: SettingDef) -> str:
    return json.dumps(definition.default)


async def seed_defaults(session: AsyncSession, *, source: str = "seed") -> int:
    """Seed missing rows. Returns the count of newly-inserted keys.

    Idempotent: existing rows are left alone (operator changes are preserved).
    """
    existing = set((await session.execute(select(Setting.key))).scalars().all())
    inserted = 0
    now = utc_now_iso()
    for key, definition in SETTINGS_CATALOGUE.items():
        if key in existing:
            continue
        await session.execute(
            insert(Setting).values(
                key=key,
                value=_encode_default(definition),
                value_type=definition.value_type,
                group_name=definition.group,
                label=definition.label,
                description=definition.description or None,
                is_secret=1 if definition.is_secret else 0,
                updated_at=now,
            )
        )
        await session.execute(
            insert(SettingChange).values(
                key=key,
                old_value=None,
                new_value=_redact(definition, _encode_default(definition)),
                changed_at=now,
                source=source,
            )
        )
        inserted += 1
    await session.commit()
    return inserted


def _redact(definition: SettingDef, value: str | None) -> str | None:
    if value is None:
        return None
    return "***" if definition.is_secret else value
