"""Idempotent seed of the settings catalogue defaults.

Inserts a row for every key in `SETTINGS_CATALOGUE` that doesn't already
exist. Never overwrites operator changes.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kerotrack.models.base import utc_now_iso
from kerotrack.models.setting import Setting
from kerotrack.models.setting_change import SettingChange
from kerotrack.settings.schema import SETTINGS_CATALOGUE, SettingDef


# Keys that have been removed from the catalogue and should be cleaned up
# from the live DB on the next start (B5: prices.homefuelsdirect_url was
# renamed to prices.yournrg_url after the upstream domestic page died).
RETIRED_KEYS: frozenset[str] = frozenset(
    {
        "prices.homefuelsdirect_url",
    }
)


def _encode_default(definition: SettingDef) -> str:
    return json.dumps(definition.default)


async def seed_defaults(session: AsyncSession, *, source: str = "seed") -> int:
    """Seed missing rows. Returns the count of newly-inserted keys.

    Idempotent: existing rows are left alone (operator changes are preserved).
    """
    existing = set((await session.execute(select(Setting.key))).scalars().all())

    # Clean up retired keys (B5).
    retired_present = existing & RETIRED_KEYS
    if retired_present:
        await session.execute(
            delete(Setting).where(Setting.key.in_(retired_present))
        )
        existing -= retired_present

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


# Old default -> new default, per key. Only rows still holding the OLD default
# exactly are rewritten; operator customisations are left alone.
DEFAULT_VALUE_REWRITES: dict[str, dict[str, str]] = {
    "schedule.analysis_cron": {"0 6 * * 0": "0 6 * * sun"},
    "schedule.cost_analysis_cron": {"0 7 * * 0": "0 7 * * sun"},
    "schedule.notifier_cron": {"0 8 * * 0": "0 8 * * *"},
}


async def migrate_default_values(session: AsyncSession) -> int:
    """Rewrite stored values that still equal a superseded default.

    Returns the number of rows rewritten. Idempotent.
    """
    rows = (
        await session.execute(
            select(Setting).where(Setting.key.in_(DEFAULT_VALUE_REWRITES))
        )
    ).scalars().all()
    changed = 0
    now = utc_now_iso()
    for row in rows:
        try:
            current = json.loads(row.value)
        except (TypeError, ValueError):
            continue
        new = DEFAULT_VALUE_REWRITES[row.key].get(current) if isinstance(current, str) else None
        if new is None:
            continue
        old_encoded = row.value
        new_encoded = json.dumps(new)
        await session.execute(
            update(Setting)
            .where(Setting.key == row.key)
            .values(value=new_encoded, updated_at=now)
        )
        await session.execute(
            insert(SettingChange).values(
                key=row.key,
                old_value=old_encoded,
                new_value=new_encoded,
                changed_at=now,
                source="migration",
            )
        )
        changed += 1
    await session.commit()
    return changed
