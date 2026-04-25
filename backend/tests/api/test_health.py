"""/api/health payload shape per spec §6.7."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    db = tmp_path / "health.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db.as_posix()}")
    monkeypatch.setenv("APP_SECRET_KEY", "0" * 64)
    from kerotrack.bootstrap import reset_bootstrap_cache
    reset_bootstrap_cache()

    from kerotrack.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
    reset_bootstrap_cache()


def test_health_empty_db(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["mqtt_connected"] is False
    assert body["last_reading_at"] is None
    assert body["age_seconds"] is None
    assert body["scheduler_running"] is False


def test_health_reflects_latest_reading(client: TestClient) -> None:
    # Insert a reading directly via the engine on app.state; the health
    # endpoint should pick it up.
    import asyncio

    from kerotrack.models.reading import Reading
    app = client.app  # type: ignore[attr-defined]
    sf = app.state.session_factory

    async def _insert() -> None:
        async with sf() as session:
            session.add(
                Reading(
                    date="2026-04-25 12:00:00",
                    id="probe",
                    temperature=18.0,
                    litres_remaining=900.0,
                )
            )
            await session.commit()

    asyncio.run(_insert())

    resp = client.get("/api/health").json()
    assert resp["last_reading_at"] == "2026-04-25 12:00:00"
    assert resp["age_seconds"] is not None
