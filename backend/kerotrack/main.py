"""FastAPI app factory.

Phase 0 stub — exposes a single health endpoint so the deploy ritual can be
verified end-to-end before any real lifespan wiring lands. Subsequent phases
replace the stub with a real lifespan that bootstraps the DB, settings, MQTT
ingest and the scheduler.
"""

from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="KeroTrack v2", version="0.0.0")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "scaffold"}

    return app


app = create_app()
