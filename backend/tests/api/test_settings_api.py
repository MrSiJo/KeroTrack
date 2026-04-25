"""Settings API tests using FastAPI's httpx client."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kerotrack.api.errors import install_error_handlers
from kerotrack.api.routes.settings import router as settings_router
from kerotrack.db import init_engine, session_factory
from kerotrack.db_migrate import ensure_schema
from kerotrack.settings.seeds import seed_defaults
from kerotrack.settings.service import SettingsService


@pytest.fixture
def app(tmp_path: Path) -> Iterator[FastAPI]:
    db_path = tmp_path / "settings_api.db"
    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    fastapi_app = FastAPI(title="settings-api-test")
    install_error_handlers(fastapi_app)
    fastapi_app.include_router(settings_router)

    @fastapi_app.on_event("startup")
    async def _startup() -> None:
        engine = init_engine(url)
        await ensure_schema(engine)
        sf = session_factory(engine)
        async with sf() as session:
            await seed_defaults(session)
        fastapi_app.state.engine = engine
        fastapi_app.state.session_factory = sf
        fastapi_app.state.settings_service = SettingsService(sf)

    @fastapi_app.on_event("shutdown")
    async def _shutdown() -> None:
        await fastapi_app.state.engine.dispose()

    yield fastapi_app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_get_schema_returns_full_catalogue(client: TestClient) -> None:
    resp = client.get("/api/settings/schema")
    assert resp.status_code == 200
    data = resp.json()
    keys = {row["key"] for row in data["catalogue"]}
    assert "tank.capacity_l" in keys
    assert "mqtt.password" in keys
    pw = next(r for r in data["catalogue"] if r["key"] == "mqtt.password")
    assert pw["is_secret"] is True
    assert pw["default"] == "********"


def test_list_settings_groups_and_redacts(client: TestClient) -> None:
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "groups" in data
    assert "tank" in data["groups"]
    pw = next(
        r for r in data["items"] if r["key"] == "mqtt.password"
    )
    assert pw["value"] == "********"


def test_get_setting_round_trip_and_secret_mask(client: TestClient) -> None:
    r1 = client.put("/api/settings/tank.capacity_l", json={"value": 1500.5})
    assert r1.status_code == 200
    assert r1.json()["value"] == 1500.5

    r2 = client.get("/api/settings/tank.capacity_l")
    assert r2.json()["value"] == 1500.5

    r3 = client.put("/api/settings/mqtt.password", json={"value": "hunter2"})
    assert r3.status_code == 200
    assert r3.json()["value"] == "********"
    r4 = client.get("/api/settings/mqtt.password")
    assert r4.json()["value"] == "********"


def test_unknown_key_returns_400(client: TestClient) -> None:
    resp = client.put("/api/settings/no.such.key", json={"value": 1})
    assert resp.status_code == 400
    assert resp.json()["error"] == "unknown_setting"


def test_type_mismatch_returns_422(client: TestClient) -> None:
    resp = client.put("/api/settings/mqtt.port", json={"value": "not-an-int"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_int"
    assert resp.json()["field"] == "mqtt.port"


def test_invalid_cron_returns_422(client: TestClient) -> None:
    resp = client.put(
        "/api/settings/schedule.notifier_cron", json={"value": "not a cron"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_cron"


def test_bulk_put(client: TestClient) -> None:
    resp = client.put(
        "/api/settings",
        json={"tank.capacity_l": 2000, "currency.symbol": "$"},
    )
    assert resp.status_code == 200
    saved = set(resp.json()["saved"])
    assert saved == {"tank.capacity_l", "currency.symbol"}
    follow = client.get("/api/settings/tank.capacity_l").json()["value"]
    assert follow == 2000.0


def test_reset_returns_to_default(client: TestClient) -> None:
    client.put("/api/settings/tank.capacity_l", json={"value": 9999})
    resp = client.post("/api/settings/tank.capacity_l/reset")
    assert resp.status_code == 200
    assert resp.json()["value"] == 1225.0


def test_changes_endpoint_records_audit(client: TestClient) -> None:
    client.put("/api/settings/currency.symbol", json={"value": "$"})
    resp = client.get("/api/settings/changes", params={"key": "currency.symbol"})
    assert resp.status_code == 200
    changes = resp.json()["changes"]
    assert any(c["new_value"] == '"$"' for c in changes)


def test_changes_redacts_secret(client: TestClient) -> None:
    client.put("/api/settings/mqtt.password", json={"value": "hunter2"})
    resp = client.get("/api/settings/changes", params={"key": "mqtt.password"})
    rows = resp.json()["changes"]
    assert any(r["new_value"] == "***" for r in rows)
    assert all("hunter2" not in (r.get("new_value") or "") for r in rows)
