"""Idempotent schema bootstrap.

Brings up every table the v2 system needs:

- v1-compatible: readings, analysis_results, refill_periods, actual_refill_costs,
  hdd_data, cost_analysis
- v2 additions: settings, setting_changes, users (Phase 2.5)

`ensure_schema` is idempotent — calling it twice on an empty DB and once-then-once
again on a populated DB both end with the same schema and the same row counts.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from kerotrack.models.base import Base

# Importing each model registers the mapped class on `Base.metadata`. Order
# doesn't matter for create_all but we keep them grouped.
from kerotrack.models import setting as _setting  # noqa: F401
from kerotrack.models import setting_change as _setting_change  # noqa: F401
from kerotrack.models import reading as _reading  # noqa: F401
from kerotrack.models import raw_capture as _raw_capture  # noqa: F401
from kerotrack.models import analysis_result as _ar  # noqa: F401
from kerotrack.models import refill as _refill  # noqa: F401
from kerotrack.models import refill_period as _rp  # noqa: F401
from kerotrack.models import hdd as _hdd  # noqa: F401
from kerotrack.models import cost_analysis as _ca  # noqa: F401
from kerotrack.models import user as _user  # noqa: F401
from kerotrack.models import monthly_ppl as _mppl  # noqa: F401
from kerotrack.models import runway_projection as _rwp  # noqa: F401


_COLUMN_ADDITIONS: dict[str, dict[str, str]] = {
    "analysis_results": {"heating_estimate_basis": "TEXT"},
    "cost_analysis": {"days_since_period_end": "INTEGER"},
}
_ALLOWED_TYPES = {"TEXT", "INTEGER", "REAL", "FLOAT"}


async def ensure_columns(conn: AsyncConnection, table: str, columns: dict[str, str]) -> list[str]:
    """Idempotently add columns to an existing table.

    Args:
        conn: Active AsyncConnection in a transaction
        table: Table name (validated as identifier)
        columns: Mapping of column name to SQL type

    Returns:
        List of column names that were added (skips if already present)

    Raises:
        ValueError: If table or column name is not a valid identifier, or type is not allowed
    """
    if not table.isidentifier():
        raise ValueError(f"bad table name {table!r}")
    existing = {r[1] for r in (await conn.execute(text(f"PRAGMA table_info({table})"))).all()}  # nosec B608  # noqa: S608
    added: list[str] = []
    for name, col_type in columns.items():
        if name in existing:
            continue
        if not name.isidentifier() or col_type not in _ALLOWED_TYPES:
            raise ValueError(f"bad column spec {name} {col_type}")
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"))  # nosec B608  # noqa: S608
        added.append(name)
    return added


async def ensure_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for table, cols in _COLUMN_ADDITIONS.items():
            await ensure_columns(conn, table, cols)
