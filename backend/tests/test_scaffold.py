"""Smoke test — the FastAPI app boots with the right title."""

from __future__ import annotations

import pytest


def test_app_imports_with_correct_title(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", "0" * 64)
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'scaffold.db').as_posix()}"
    )
    from kerotrack.bootstrap import reset_bootstrap_cache

    reset_bootstrap_cache()
    from kerotrack.main import create_app

    app = create_app()
    assert app.title == "KeroTrack v2"
    reset_bootstrap_cache()
