"""DST regression — payloads without `time` get a local-tz timestamp,
and /api/health computes age against the same zone.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    db = tmp_path / "dst.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db.as_posix()}")
    monkeypatch.setenv("APP_SECRET_KEY", "0" * 64)
    monkeypatch.setenv("TZ", "Europe/London")
    from kerotrack.bootstrap import reset_bootstrap_cache

    reset_bootstrap_cache()
    from kerotrack.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
    reset_bootstrap_cache()


def test_normalised_payload_uses_local_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Europe/London")
    monkeypatch.setenv("APP_SECRET_KEY", "0" * 64)
    from kerotrack.bootstrap import reset_bootstrap_cache

    reset_bootstrap_cache()
    from kerotrack.ingest.mqtt import _normalise_payload

    payload = _normalise_payload({"model": "Oil-SonicAdv", "id": 1})
    # The time string should be parseable as naive but represent local now.
    ts = datetime.strptime(payload["time"], "%Y-%m-%d %H:%M:%S")
    london = datetime.now(tz=ZoneInfo("Europe/London")).replace(tzinfo=None)
    diff = abs((ts - london).total_seconds())
    assert diff < 5
    reset_bootstrap_cache()


def test_health_age_is_close_to_zero_for_just_now_reading(client: TestClient) -> None:
    """A reading inserted at local-now should have age_seconds ~ 0,
    proving /api/health and the writer agree on the zone."""
    import asyncio
    from kerotrack.clock import local_now_str
    from kerotrack.models.reading import Reading

    sf = client.app.state.session_factory  # type: ignore[attr-defined]
    now_str = local_now_str()

    async def _seed() -> None:
        async with sf() as session:
            session.add(
                Reading(date=now_str, id="probe", litres_remaining=900.0)
            )
            await session.commit()

    asyncio.run(_seed())

    body = client.get("/api/health").json()
    assert body["last_reading_at"] == now_str
    assert body["age_seconds"] is not None
    # Generous bound — in CI on a slow host the request might take a second
    # or two — but a UTC/local mismatch would manifest as ~3600s in BST.
    assert 0 <= body["age_seconds"] < 60
