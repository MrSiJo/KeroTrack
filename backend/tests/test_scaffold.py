"""Smoke test — the FastAPI app boots with the right title."""

from __future__ import annotations


def test_app_imports_with_correct_title() -> None:
    from kerotrack.main import app

    assert app.title == "KeroTrack v2"
