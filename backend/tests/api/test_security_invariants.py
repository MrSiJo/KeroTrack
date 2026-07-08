"""Security invariants — the contract this app must always uphold.

These tests pin down behaviour that's easy to regress when adding new routes
or middleware. If any of them fail, do not "fix the test" — fix the code.

The invariants:

1. Every mounted `/api/*` route either appears in `EXEMPT_PATHS` or returns
   401 when called without a session.
2. Mutating verbs on authenticated routes require the `X-CSRF-Token` header.
3. `/api/setup` is one-shot: a second call after a user exists returns 409,
   regardless of payload.
4. The login rate limiter trips on the 6th attempt within a minute.
5. The session cookie carries `HttpOnly` and `SameSite=Lax`, and `Secure`
   when `SESSION_COOKIE_SECURE=true`.
6. Password policy: `/api/setup` and `/api/auth/change-password` reject any
   password shorter than 12 characters.
7. Login does not leak whether the username exists (same status + code for
   wrong-password and unknown-user).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route

from kerotrack.api.auth_middleware import EXEMPT_PATHS
from kerotrack.api.csrf import CSRF_EXEMPT_PATHS, MUTATING_METHODS


# --------------------------------------------------------------------- fixtures


def _build_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *,
               cookie_secure: str = "false"):
    db = tmp_path / "sec.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db.as_posix()}")
    monkeypatch.setenv("APP_SECRET_KEY", "0" * 64)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", cookie_secure)
    from kerotrack.bootstrap import reset_bootstrap_cache

    reset_bootstrap_cache()
    from kerotrack.main import create_app

    return create_app()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    app = _build_app(monkeypatch, tmp_path)
    app.state.limiter.enabled = False
    with TestClient(app) as c:
        yield c
    app.state.limiter.enabled = True
    from kerotrack.bootstrap import reset_bootstrap_cache
    reset_bootstrap_cache()


def _setup_and_login(client: TestClient) -> str:
    client.post(
        "/api/setup",
        json={"username": "admin", "password": "hunter2-strong-pw"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "hunter2-strong-pw"},
    )
    return resp.json()["csrf_token"]


# ------------------------------------------------------- 1. auth gate coverage


def _api_routes(app) -> list[tuple[str, set[str]]]:
    """Return (path, methods) for every `/api/*` HTTP route mounted on `app`."""
    out: list[tuple[str, set[str]]] = []
    for r in app.routes:
        if not isinstance(r, Route):
            continue
        if not r.path.startswith("/api/"):
            continue
        methods = (r.methods or set()) - {"HEAD", "OPTIONS"}
        if methods:
            out.append((r.path, methods))
    return out


def _path_matches_exempt(path: str) -> bool:
    """Allow exact match OR templated routes whose static prefix is exempt.

    The middleware compares `request.url.path`, which for templated routes
    is the concrete path. For coverage we treat a route exempt iff its
    template starts with one of the exempt entries.
    """
    if path in EXEMPT_PATHS:
        return True
    for exempt in EXEMPT_PATHS:
        if path == exempt or path.startswith(exempt + "/"):
            return True
    return False


def test_every_api_route_is_either_exempt_or_requires_auth(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    app = _build_app(monkeypatch, tmp_path)
    app.state.limiter.enabled = False
    with TestClient(app) as c:
        for path, methods in _api_routes(app):
            if _path_matches_exempt(path):
                continue
            # Substitute placeholders with safe-ish values so the route
            # actually dispatches rather than 404'ing on a literal `{x}`.
            concrete = path.replace("{key}", "tank.capacity_l")
            concrete = concrete.replace("{date_id}", "2024-01-01%2000%3A00%3A00")
            concrete = concrete.replace("{refill_date}", "2024-01-01")
            concrete = concrete.replace("{name}", "analysis")
            for method in methods:
                resp = c.request(method, concrete, json={})
                assert resp.status_code == 401, (
                    f"{method} {concrete} returned {resp.status_code}, "
                    f"expected 401 (route is not in EXEMPT_PATHS)"
                )
                assert resp.json().get("error") == "auth_required"


# ----------------------------------------------------------- 2. CSRF on writes


def test_mutating_routes_require_csrf_header(client: TestClient) -> None:
    _setup_and_login(client)
    # Pick a representative mutating endpoint that isn't CSRF-exempt.
    assert "/api/auth/login" in CSRF_EXEMPT_PATHS  # sanity
    for method in MUTATING_METHODS:
        # /api/admin/reload-settings is auth-gated and CSRF-checked.
        resp = client.request(method, "/api/admin/reload-settings", json={})
        # Method may be 405 if not registered for that verb — only assert
        # on the verb that actually exists (POST).
        if method != "POST":
            continue
        assert resp.status_code == 403
        assert resp.json()["error"] == "csrf_missing"


# --------------------------------------------------- 3. setup is truly one-shot


def test_setup_is_one_shot(client: TestClient) -> None:
    first = client.post(
        "/api/setup",
        json={"username": "admin", "password": "hunter2-strong-pw"},
    )
    assert first.status_code == 200
    # Different username, valid payload — must still be rejected.
    second = client.post(
        "/api/setup",
        json={"username": "intruder", "password": "another-strong-pw"},
    )
    assert second.status_code == 409
    assert second.json()["detail"]["error"] == "already_setup"
    # Same username, different password — must also be rejected.
    third = client.post(
        "/api/setup",
        json={"username": "admin", "password": "different-strong-pw"},
    )
    assert third.status_code == 409


# ---------------------------------------------------- 4. login rate limit trips


def test_login_rate_limit_trips_after_five(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    app = _build_app(monkeypatch, tmp_path)
    # Limiter explicitly LEFT enabled for this test.
    with TestClient(app) as c:
        c.post(
            "/api/setup",
            json={"username": "admin", "password": "hunter2-strong-pw"},
        )
        # Five wrong-password attempts: each returns 401, no throttle yet.
        for _ in range(5):
            resp = c.post(
                "/api/auth/login",
                json={"username": "admin", "password": "wrong-attempt"},
            )
            assert resp.status_code == 401
        # Sixth attempt is throttled.
        sixth = c.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong-attempt"},
        )
        assert sixth.status_code == 429
    from kerotrack.bootstrap import reset_bootstrap_cache
    reset_bootstrap_cache()


# ------------------------------------------------------ 5. session cookie flags


def test_session_cookie_flags_when_secure_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    app = _build_app(monkeypatch, tmp_path, cookie_secure="true")
    app.state.limiter.enabled = False
    # base_url over https so the TestClient's httpx transport ships the
    # Secure cookie back to us.
    with TestClient(app, base_url="https://testserver") as c:
        c.post(
            "/api/setup",
            json={"username": "admin", "password": "hunter2-strong-pw"},
        )
        login = c.post(
            "/api/auth/login",
            json={"username": "admin", "password": "hunter2-strong-pw"},
        )
        assert login.status_code == 200
        set_cookie = login.headers.get("set-cookie", "").lower()
        assert "kerotrack_session=" in set_cookie
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie
        assert "secure" in set_cookie
    app.state.limiter.enabled = True
    from kerotrack.bootstrap import reset_bootstrap_cache
    reset_bootstrap_cache()


def test_session_cookie_omits_secure_when_disabled(client: TestClient) -> None:
    # `client` fixture sets SESSION_COOKIE_SECURE=false.
    client.post(
        "/api/setup",
        json={"username": "admin", "password": "hunter2-strong-pw"},
    )
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "hunter2-strong-pw"},
    )
    set_cookie = login.headers.get("set-cookie", "").lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    # Match the attribute exactly so the substring `secure` doesn't match
    # against e.g. an unrelated value containing the word.
    assert "; secure" not in set_cookie


# ------------------------------------------------------- 6. password policy


def test_setup_rejects_short_password(client: TestClient) -> None:
    resp = client.post(
        "/api/setup",
        json={"username": "admin", "password": "short"},
    )
    # Pydantic min_length fires before the handler.
    assert resp.status_code == 422


def test_change_password_rejects_short_new(client: TestClient) -> None:
    token = _setup_and_login(client)
    resp = client.post(
        "/api/auth/change-password",
        headers={"X-CSRF-Token": token},
        json={"old_password": "hunter2-strong-pw", "new_password": "short"},
    )
    assert resp.status_code == 422


# -------------------------------------------------- 7. login enumeration parity


def test_login_does_not_leak_user_existence(client: TestClient) -> None:
    client.post(
        "/api/setup",
        json={"username": "admin", "password": "hunter2-strong-pw"},
    )
    wrong_pw = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong-but-long-enough"},
    )
    unknown = client.post(
        "/api/auth/login",
        json={"username": "ghost", "password": "wrong-but-long-enough"},
    )
    assert wrong_pw.status_code == unknown.status_code == 401
    assert (
        wrong_pw.json()["detail"]["error"]
        == unknown.json()["detail"]["error"]
        == "auth_required"
    )


# -------------------------------------------------- 8. change-password throttle


def test_change_password_rate_limit_trips_after_five(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """change-password is auth+CSRF gated AND rate-limited like login."""
    app = _build_app(monkeypatch, tmp_path)
    # Limiter explicitly LEFT enabled for this test. The limiter is a module
    # singleton with in-memory storage shared across tests, so reset its
    # counters first — otherwise the single login below may already be
    # throttled by an earlier test using the same `testclient` key.
    app.state.limiter.reset()
    with TestClient(app) as c:
        c.post(
            "/api/setup",
            json={"username": "admin", "password": "hunter2-strong-pw"},
        )
        login = c.post(
            "/api/auth/login",
            json={"username": "admin", "password": "hunter2-strong-pw"},
        )
        token = login.json()["csrf_token"]
        headers = {"X-CSRF-Token": token}
        body = {
            "old_password": "wrong-old-password",
            "new_password": "another-strong-pw",
        }
        # Five wrong-old-password attempts: each is a 4xx auth error, not 429.
        for _ in range(5):
            resp = c.post(
                "/api/auth/change-password", headers=headers, json=body
            )
            assert resp.status_code != 429
        # Sixth attempt is throttled.
        sixth = c.post(
            "/api/auth/change-password", headers=headers, json=body
        )
        assert sixth.status_code == 429
    from kerotrack.bootstrap import reset_bootstrap_cache
    reset_bootstrap_cache()


# ----------------------------------------------- 9. SSRF guard on settings URLs
#
# The contract (CLAUDE.md → "Outbound HTTP / SSRF") requires scheme validation
# plus an allowlist on operator-set fetch URLs. These exercise the guard at the
# write path (`SettingsService.set`). Each builds its own engine/service and
# runs under a fresh event loop so it stays independent of the sync TestClient.


def _run_set(tmp_path: Path, key: str, value: object) -> None:
    """Seed a settings DB and call `set(key, value)` under a fresh loop."""
    import asyncio

    from kerotrack.db import init_engine, session_factory
    from kerotrack.db_migrate import ensure_schema
    from kerotrack.settings.seeds import seed_defaults
    from kerotrack.settings.service import SettingsService

    db = tmp_path / "ssrf.db"

    async def _run() -> None:
        engine = init_engine(f"sqlite+aiosqlite:///{db.as_posix()}")
        await ensure_schema(engine)
        sf = session_factory(engine)
        async with sf() as session:
            await seed_defaults(session)
        svc = SettingsService(sf)
        try:
            await svc.set(key, value, source="test")
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_price_url_rejects_non_http_scheme(tmp_path: Path) -> None:
    """Operator-set fetch URLs must be http/https (SSRF contract)."""
    from kerotrack.settings.service import SettingError

    with pytest.raises(SettingError) as exc:
        _run_set(tmp_path, "prices.boilerjuice_url", "file:///etc/passwd")
    assert exc.value.code in {"invalid_url_scheme", "invalid_url"}


def test_price_url_rejects_off_allowlist_host(tmp_path: Path) -> None:
    from kerotrack.settings.service import SettingError

    with pytest.raises(SettingError) as exc:
        _run_set(tmp_path, "prices.boilerjuice_url", "https://attacker.example/x")
    assert exc.value.code == "url_host_not_allowed"


def test_apprise_url_rejects_internal_host(tmp_path: Path) -> None:
    from kerotrack.settings.service import SettingError

    with pytest.raises(SettingError) as exc:
        _run_set(
            tmp_path, "notifications.apprise_urls", ["gotify://127.0.0.1/token"]
        )
    assert exc.value.code == "url_host_internal"


def test_price_url_allowlisted_host_passes(tmp_path: Path) -> None:
    """The catalogue defaults must remain settable (no false positives)."""
    _run_set(
        tmp_path,
        "prices.boilerjuice_url",
        "https://www.boilerjuice.com/heating-oil-prices-england/",
    )
