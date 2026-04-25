"""End-to-end auth flow tests against the real `create_app()`."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    db = tmp_path / "auth.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db.as_posix()}")
    monkeypatch.setenv("APP_SECRET_KEY", "0" * 64)
    from kerotrack.bootstrap import reset_bootstrap_cache
    reset_bootstrap_cache()

    from kerotrack.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
    reset_bootstrap_cache()


def _setup(client: TestClient, *, username: str = "admin", password: str = "hunter2") -> None:
    resp = client.post("/api/setup", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text


def _login(client: TestClient, *, username: str = "admin", password: str = "hunter2") -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["csrf_token"]


# ----------------------------------------------------------- setup flow


def test_setup_status_pre_and_post(client: TestClient) -> None:
    pre = client.get("/api/setup/status")
    assert pre.status_code == 200
    assert pre.json() == {"needs_setup": True}
    _setup(client)
    post = client.get("/api/setup/status")
    assert post.json() == {"needs_setup": False}


def test_setup_rejects_second_user(client: TestClient) -> None:
    _setup(client)
    resp = client.post(
        "/api/setup", json={"username": "second", "password": "x"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "already_setup"


# ----------------------------------------------------------- login / me / logout


def test_login_success_returns_csrf_token(client: TestClient) -> None:
    _setup(client)
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "hunter2"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "admin"
    assert body["csrf_token"] and len(body["csrf_token"]) >= 32


def test_login_wrong_password(client: TestClient) -> None:
    _setup(client)
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "nope"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "auth_required"


def test_me_requires_session(client: TestClient) -> None:
    _setup(client)
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_after_login(client: TestClient) -> None:
    _setup(client)
    token = _login(client)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "admin"
    assert me.json()["csrf_token"] == token


def test_logout_clears_session(client: TestClient) -> None:
    _setup(client)
    token = _login(client)
    out = client.post("/api/auth/logout", headers={"X-CSRF-Token": token})
    assert out.status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 401


# ----------------------------------------------------------- change password


def test_change_password_rotates(client: TestClient) -> None:
    _setup(client)
    token = _login(client)
    resp = client.post(
        "/api/auth/change-password",
        headers={"X-CSRF-Token": token},
        json={"old_password": "hunter2", "new_password": "newpass"},
    )
    assert resp.status_code == 200
    # Old creds fail, new creds work.
    bad = client.post(
        "/api/auth/login", json={"username": "admin", "password": "hunter2"}
    )
    assert bad.status_code == 401
    good = client.post(
        "/api/auth/login", json={"username": "admin", "password": "newpass"}
    )
    assert good.status_code == 200


def test_change_password_wrong_old(client: TestClient) -> None:
    _setup(client)
    token = _login(client)
    resp = client.post(
        "/api/auth/change-password",
        headers={"X-CSRF-Token": token},
        json={"old_password": "wrong", "new_password": "anything"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "invalid_password"


def test_change_password_requires_csrf(client: TestClient) -> None:
    _setup(client)
    _login(client)
    resp = client.post(
        "/api/auth/change-password",
        json={"old_password": "hunter2", "new_password": "newpass"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "csrf_missing"


# ----------------------------------------------------------- middleware gate


def test_health_is_exempt(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_settings_requires_auth(client: TestClient) -> None:
    _setup(client)
    resp = client.get("/api/settings")
    assert resp.status_code == 401
    assert resp.json()["error"] == "auth_required"


def test_settings_with_session_works(client: TestClient) -> None:
    _setup(client)
    token = _login(client)
    resp = client.get("/api/settings")
    assert resp.status_code == 200

    # Mutating call without CSRF: forbidden.
    bad = client.put("/api/settings/tank.capacity_l", json={"value": 1500})
    assert bad.status_code == 403
    assert bad.json()["error"] == "csrf_missing"

    # With CSRF: succeeds.
    ok = client.put(
        "/api/settings/tank.capacity_l",
        headers={"X-CSRF-Token": token},
        json={"value": 1500},
    )
    assert ok.status_code == 200
    assert ok.json()["value"] == 1500.0
