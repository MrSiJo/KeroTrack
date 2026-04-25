"""FastAPI app factory + lifespan.

Phase 1 wires the DB engine, runs schema migrations, seeds settings defaults,
and exposes the settings API + the scaffold health endpoint. Phase 2 replaces
the health stub with a real status payload; Phase 2.5 layers in auth.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from kerotrack.api.errors import install_error_handlers
from kerotrack.api.routes.settings import router as settings_router
from kerotrack.bootstrap import get_bootstrap
from kerotrack.db import init_engine, session_factory
from kerotrack.db_migrate import ensure_schema
from kerotrack.settings.seeds import seed_defaults
from kerotrack.settings.service import SettingsService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    boot = get_bootstrap()
    engine = init_engine(boot.database_url)
    await ensure_schema(engine)
    sf = session_factory(engine)
    async with sf() as session:
        await seed_defaults(session)

    settings_service = SettingsService(sf)

    app.state.bootstrap = boot
    app.state.engine = engine
    app.state.session_factory = sf
    app.state.settings_service = settings_service
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="KeroTrack v2", version="0.0.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(settings_router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        # Phase 2 replaces this with a real payload.
        return {"status": "scaffold"}

    return app


app = create_app()
