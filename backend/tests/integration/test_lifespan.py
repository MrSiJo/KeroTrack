"""Lifespan brings up engine, schema, settings, MQTT, PriceService — and
tears down cleanly."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from kerotrack.ingest.mqtt import MqttIngest
from kerotrack.main import create_app
from kerotrack.models.setting import Setting
from kerotrack.prices.service import PriceService
from kerotrack.scheduler.service import SchedulerService


pytestmark = pytest.mark.asyncio


async def test_lifespan_starts_and_stops(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "lifespan.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db.as_posix()}")
    monkeypatch.setenv("APP_SECRET_KEY", "0" * 64)
    from kerotrack.bootstrap import reset_bootstrap_cache
    reset_bootstrap_cache()

    app = create_app()

    async with app.router.lifespan_context(app):
        # DB engine + settings.
        assert app.state.engine is not None
        assert app.state.session_factory is not None
        assert app.state.settings_service is not None
        async with app.state.session_factory() as session:
            keys = (await session.execute(select(Setting.key))).scalars().all()
        assert "tank.capacity_l" in keys

        # A8: live MQTT ingest + PriceService are wired into app.state.
        assert isinstance(app.state.mqtt, MqttIngest)
        assert app.state.publisher is app.state.mqtt.publisher
        assert isinstance(app.state.prices, PriceService)
        assert isinstance(app.state.scheduler, SchedulerService)
        assert app.state.pubsub is not None
        assert app.state.mqtt_feed is not None

    # After exit, the price client is closed and the DB file exists (proves
    # the engine actually opened a connection during the lifespan).
    assert app.state.prices._client is None
    assert db.exists()
    reset_bootstrap_cache()
