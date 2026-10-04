"""Test ensure_columns idempotent schema migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text

from kerotrack.db import init_engine
from kerotrack.db_migrate import ensure_schema


@pytest.mark.asyncio
async def test_ensure_schema_adds_missing_columns_to_old_tables(tmp_path: Path) -> None:
    """Verify ensure_schema adds heating_estimate_basis and days_since_period_end columns."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE analysis_results (latest_reading_date TEXT PRIMARY KEY)")
    con.execute("CREATE TABLE cost_analysis (analysis_date TEXT PRIMARY KEY)")
    con.commit()
    con.close()

    eng = init_engine(f"sqlite+aiosqlite:///{db.as_posix()}")
    await ensure_schema(eng)
    await ensure_schema(eng)  # idempotent

    async with eng.connect() as conn:
        cols = [r[1] for r in (await conn.execute(text("PRAGMA table_info(analysis_results)"))).all()]
        assert "heating_estimate_basis" in cols
        cols = [r[1] for r in (await conn.execute(text("PRAGMA table_info(cost_analysis)"))).all()]
        assert "days_since_period_end" in cols

    await eng.dispose()
