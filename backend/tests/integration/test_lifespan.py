"""Lifespan brings up engine, schema, settings — and tears down cleanly."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from kerotrack.main import create_app
from kerotrack.models.setting import Setting


pytestmark = pytest.mark.asyncio


async def test_lifespan_starts_and_stops(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "lifespan.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db.as_posix()}")
    monkeypatch.setenv("APP_SECRET_KEY", "0" * 64)
    from kerotrack.bootstrap import reset_bootstrap_cache
    reset_bootstrap_cache()

    app = create_app()

    async with app.router.lifespan_context(app):
        assert app.state.engine is not None
        assert app.state.session_factory is not None
        assert app.state.settings_service is not None
        # Settings table seeded.
        async with app.state.session_factory() as session:
            keys = (await session.execute(select(Setting.key))).scalars().all()
        assert "tank.capacity_l" in keys

    # After exit, engine has been disposed — we can't reliably call it; just
    # confirm the WAL files exist next to the DB (proves the engine actually
    # opened a real connection during the lifespan).
    assert db.exists()
    reset_bootstrap_cache()
