"""Phase 0 scaffold proof — the FastAPI app boots and returns the stub health payload."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_app_imports_with_correct_title() -> None:
    from kerotrack.main import app

    assert app.title == "KeroTrack v2"


def test_health_returns_scaffold_status() -> None:
    from kerotrack.main import app

    client = TestClient(app)
    resp = client.get("/api/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "scaffold"}
