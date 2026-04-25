"""FastAPI app factory + lifespan.

Phases 0–2 stood up the DB + settings + health. Phase 2.5 wires the
JobTrack-pattern auth stack:

  Session → RequireAuth → CSRF → route

Starlette applies middleware in reverse-add order, so we add them in the
opposite order: CSRF first, then RequireAuth, then Session. The result on
the request path is exactly the spec §6.6 order.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from kerotrack.api.auth_middleware import RequireAuthMiddleware
from kerotrack.api.csrf import CSRFMiddleware
from kerotrack.api.errors import install_error_handlers
from kerotrack.api.routes.auth import router as auth_router
from kerotrack.api.routes.health import router as health_router
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
    app.state.secret_key = boot.app_secret_key
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="KeroTrack v2", version="0.0.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(settings_router)

    boot = get_bootstrap()
    secret_key = boot.require_secret()

    # Add in reverse order so the runtime chain is Session → RequireAuth → CSRF.
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(RequireAuthMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        https_only=False,
        same_site="lax",
        session_cookie="kerotrack_session",
    )
    return app


# Production entrypoint via uvicorn `--factory kerotrack.main:create_app`.
# We do not instantiate at module import time so that test imports without a
# bound APP_SECRET_KEY remain non-fatal.

