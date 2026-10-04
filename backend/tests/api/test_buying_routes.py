"""Buying API routes: summary, quotes history, run, calibrate."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kerotrack.clock import local_now_str
from kerotrack.models.buying_state import BuyingState
from kerotrack.models.price_quote import PriceQuote


def _setup(client: TestClient, *, username: str = "admin", password: str = "hunter2-strong-pw") -> None:
    resp = client.post("/api/setup", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text


def _login(c: TestClient, *, password: str = "hunter2-strong-pw") -> None:
    login = c.post(
        "/api/auth/login",
        json={"username": "admin", "password": password},
    )
    c.headers.update({"X-CSRF-Token": login.json()["csrf_token"]})


def _login_without_csrf(c: TestClient, *, password: str = "hunter2-strong-pw"):
    """Call login endpoint without setting the CSRF header. Returns response."""
    return c.post(
        "/api/auth/login",
        json={"username": "admin", "password": password},
    )


@pytest.fixture
def app_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[TestClient, object]]:
    db = tmp_path / "buying.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db.as_posix()}")
    monkeypatch.setenv("APP_SECRET_KEY", "0" * 64)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    from kerotrack.bootstrap import reset_bootstrap_cache

    reset_bootstrap_cache()
    from kerotrack.main import create_app

    app = create_app()
    app.state.limiter.enabled = False
    with TestClient(app) as c:
        _setup(c)
        yield c, app
    app.state.limiter.enabled = True
    reset_bootstrap_cache()


def test_unauthenticated_summary_401(app_client) -> None:
    c, _ = app_client
    assert c.get("/api/buying/summary").status_code == 401


def test_summary_empty_db_200(app_client) -> None:
    c, _ = app_client
    _login(c)
    resp = c.get("/api/buying/summary")
    assert resp.status_code == 200
    assert resp.json()["state"] == "unknown"


def test_summary_with_state(app_client) -> None:
    c, app = app_client
    _login(c)
    now = local_now_str()

    # Seed through the portal the TestClient runs the app on.
    async def _go() -> None:
        async with app.state.session_factory() as s:
            s.add(BuyingState(id=1, state="wait", updated_at=now, summary_json="{}"))
            await s.commit()

    c.portal.call(_go)
    resp = c.get("/api/buying/summary")
    assert resp.status_code == 200
    assert resp.json()["state"] == "wait"


def test_quotes_history_and_no_postcode(app_client) -> None:
    c, app = app_client
    _login(c)

    async def _go() -> None:
        async with app.state.session_factory() as s:
            s.add(
                PriceQuote(
                    fetched_at=local_now_str(),
                    supplier="Acme Oil",
                    kind="quote",
                    litres=500,
                    ppl_effective=70.0,
                    total_inc_vat=350.0,
                )
            )
            await s.commit()

    c.portal.call(_go)
    resp = c.get("/api/buying/quotes?days=30")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["supplier"] == "Acme Oil"
    assert "postcode" not in resp.text.lower()


@pytest.mark.parametrize("days", [0, 731])
def test_quotes_days_bounds(app_client, days: int) -> None:
    c, _ = app_client
    _login(c)
    assert c.get(f"/api/buying/quotes?days={days}").status_code == 422


def test_post_without_csrf_403(app_client) -> None:
    c, _ = app_client
    login = _login_without_csrf(c)
    assert login.status_code == 200
    assert c.post("/api/buying/calibrate").status_code == 403
    assert c.post("/api/buying/run").status_code == 403


def test_calibrate_returns_k(app_client) -> None:
    c, _ = app_client
    _login(c)
    resp = c.post("/api/buying/calibrate")
    assert resp.status_code == 200
    body = resp.json()
    assert "k" in body
    assert "current_burner_minutes" in body
    assert "current_hw_l_per_day" in body


def test_run_returns_summary(app_client) -> None:
    c, app = app_client
    _login(c)

    async def _fake(name: str) -> dict:
        return {"state": "buy"}

    app.state.scheduler.trigger_now = _fake
    resp = c.post("/api/buying/run")
    assert resp.status_code == 200
    assert resp.json() == {"state": "buy"}
