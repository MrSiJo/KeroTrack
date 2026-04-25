"""Engine factory pragmas + idempotent schema bootstrap."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from kerotrack.db import init_engine
from kerotrack.db_migrate import ensure_schema


pytestmark = pytest.mark.asyncio


EXPECTED_TABLES = {
    "settings",
    "setting_changes",
    "readings",
    "analysis_results",
    "actual_refill_costs",
    "refill_periods",
    "hdd_data",
    "energy_metrics",
    "cost_analysis",
}


async def test_wal_pragma_set_on_connect(tmp_path: Path) -> None:
    db = tmp_path / "wal.db"
    engine = init_engine(f"sqlite+aiosqlite:///{db.as_posix()}")
    try:
        async with engine.connect() as conn:
            mode = (
                await conn.execute(text("PRAGMA journal_mode"))
            ).scalar_one()
        assert mode.lower() == "wal"
    finally:
        await engine.dispose()


async def test_ensure_schema_creates_all_v2_tables(tmp_path: Path) -> None:
    db = tmp_path / "schema.db"
    engine = init_engine(f"sqlite+aiosqlite:///{db.as_posix()}")
    try:
        await ensure_schema(engine)
        async with engine.connect() as conn:
            tables = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names())
            )
        assert EXPECTED_TABLES.issubset(tables), (
            f"missing tables: {EXPECTED_TABLES - tables}"
        )
    finally:
        await engine.dispose()


async def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "idem.db"
    engine = init_engine(f"sqlite+aiosqlite:///{db.as_posix()}")
    try:
        await ensure_schema(engine)
        await ensure_schema(engine)  # second call must not raise
        async with engine.connect() as conn:
            tables = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names())
            )
        assert EXPECTED_TABLES.issubset(tables)
    finally:
        await engine.dispose()
