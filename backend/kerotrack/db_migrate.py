"""Idempotent schema bootstrap.

Phase 1 brings up just the settings tables. Phase 2 will extend this to cover
every v1 table plus the v2 additions; Phase 2.5 adds the `users` table.

`ensure_schema` is idempotent — calling it twice produces the same schema.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from kerotrack.models.base import Base

# Importing the modules registers the mapped classes on `Base.metadata`.
from kerotrack.models import setting as _setting_model  # noqa: F401
from kerotrack.models import setting_change as _setting_change_model  # noqa: F401


async def ensure_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
