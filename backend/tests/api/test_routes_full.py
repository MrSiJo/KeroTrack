"""End-to-end coverage of every Phase-5 read/write endpoint."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    db = tmp_path / "routes.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db.as_posix()}")
    monkeypatch.setenv("APP_SECRET_KEY", "0" * 64)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    from kerotrack.bootstrap import reset_bootstrap_cache

    reset_bootstrap_cache()
    from kerotrack.main import create_app

    app = create_app()
    app.state.limiter.enabled = False
    with TestClient(app) as c:
        # bootstrap + login so all gated routes are reachable.
        c.post(
            "/api/setup",
            json={"username": "admin", "password": "hunter2-strong-pw"},
        )
        login = c.post(
            "/api/auth/login",
            json={"username": "admin", "password": "hunter2-strong-pw"},
        )
        token = login.json()["csrf_token"]
        c.headers.update({"X-CSRF-Token": token})
        yield c
    app.state.limiter.enabled = True
    reset_bootstrap_cache()


def test_status_empty_db(client: TestClient) -> None:
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"reading": None, "analysis": None, "cost": None}


def test_readings_empty(client: TestClient) -> None:
    resp = client.get("/api/readings")
    assert resp.status_code == 200
    assert resp.json() == {"total": 0, "items": [], "limit": 200, "offset": 0}


def test_analysis_no_data_404(client: TestClient) -> None:
    assert client.get("/api/analysis/latest").status_code == 404


def test_analysis_history_returns_empty_list(client: TestClient) -> None:
    resp = client.get("/api/analysis/history")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_costs_summary_no_data_404(client: TestClient) -> None:
    assert client.get("/api/costs/summary").status_code == 404


def test_periods_empty(client: TestClient) -> None:
    resp = client.get("/api/costs/periods")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_refills_create_get_delete(client: TestClient) -> None:
    create = client.post(
        "/api/refills",
        json={"refill_date": "2026-04-25 09:00:00", "actual_volume_litres": 600.0},
    )
    assert create.status_code == 200
    items = client.get("/api/refills").json()["items"]
    assert any(r["refill_date"] == "2026-04-25 09:00:00" for r in items)

    duplicate = client.post(
        "/api/refills",
        json={"refill_date": "2026-04-25 09:00:00"},
    )
    assert duplicate.status_code == 409

    deleted = client.delete("/api/refills/2026-04-25 09:00:00")
    assert deleted.status_code == 200
    assert client.get("/api/refills").json()["items"] == []


def test_hdd_empty(client: TestClient) -> None:
    resp = client.get("/api/hdd")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_mqtt_feed_empty(client: TestClient) -> None:
    resp = client.get("/api/mqtt-feed")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_admin_unknown_job_404(client: TestClient) -> None:
    resp = client.post("/api/admin/jobs/nope/run", json={})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "unknown_job"


def test_admin_notifier_test_dispatches_skip(client: TestClient) -> None:
    # No apprise URLs configured — notifier test reports skipped.
    resp = client.post("/api/admin/jobs/notifier/run", json={"test": True})
    assert resp.status_code == 200
    assert resp.json()["sent"] is False


def test_admin_reload_settings(client: TestClient) -> None:
    resp = client.post("/api/admin/reload-settings", json={})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_readings_patch_and_delete_round_trip(client: TestClient) -> None:
    # Insert a reading directly via the engine.
    import asyncio
    from kerotrack.models.reading import Reading

    sf = client.app.state.session_factory  # type: ignore[attr-defined]

    async def _seed() -> None:
        async with sf() as session:
            session.add(
                Reading(
                    date="2026-04-25 09:00:00",
                    id="probe",
                    temperature=10.0,
                    litres_remaining=500.0,
                    air_gap_cm=80.0,
                )
            )
            await session.commit()

    asyncio.run(_seed())

    detail = client.get("/api/readings/2026-04-25 09:00:00")
    assert detail.status_code == 200

    patched = client.patch(
        "/api/readings/2026-04-25 09:00:00",
        json={"temperature": 12.5},
    )
    assert patched.status_code == 200
    assert patched.json()["temperature"] == 12.5

    deleted = client.delete("/api/readings/2026-04-25 09:00:00")
    assert deleted.status_code == 200
    assert client.get("/api/readings/2026-04-25 09:00:00").status_code == 404


def test_status_updates_after_seed(client: TestClient) -> None:
    import asyncio
    from kerotrack.models.reading import Reading

    sf = client.app.state.session_factory  # type: ignore[attr-defined]

    async def _seed() -> None:
        async with sf() as session:
            session.add(
                Reading(
                    date="2026-04-25 09:00:00",
                    id="probe",
                    litres_remaining=900.0,
                )
            )
            await session.commit()

    asyncio.run(_seed())

    body = client.get("/api/status").json()
    assert body["reading"] is not None
    assert body["reading"]["litres_remaining"] == 900.0
