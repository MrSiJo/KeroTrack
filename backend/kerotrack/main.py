"""FastAPI app factory + lifespan.

Phase 5 wires the full API surface: health, auth, settings, status,
readings, analysis, costs, refills, hdd, mqtt_feed, stream (SSE), admin.
The lifespan now also stands up the publisher, scheduler and pubsub bus
on app.state so the admin routes can drive them. The MQTT ingest task
is left dormant until the operator points `mqtt.broker` at a real
broker via Settings — keeping the host harmless for the empty-DB
scaffold deploy.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from kerotrack.api.auth_middleware import RequireAuthMiddleware
from kerotrack.api.csrf import CSRFMiddleware
from kerotrack.api.errors import install_error_handlers
from kerotrack.api.routes.admin import router as admin_router
from kerotrack.api.routes.analysis import router as analysis_router
from kerotrack.api.routes.auth import router as auth_router
from kerotrack.api.routes.costs import router as costs_router
from kerotrack.api.routes.hdd import router as hdd_router
from kerotrack.api.routes.health import router as health_router
from kerotrack.api.routes.mqtt_feed import MqttFeedRing, router as mqtt_feed_router
from kerotrack.api.routes.readings import router as readings_router
from kerotrack.api.routes.refills import router as refills_router
from kerotrack.api.routes.settings import router as settings_router
from kerotrack.api.routes.status import router as status_router
from kerotrack.api.routes.stream import router as stream_router
from kerotrack.bootstrap import get_bootstrap
from kerotrack.db import init_engine, session_factory
from kerotrack.db_migrate import ensure_schema
from kerotrack.publish.mqtt_publisher import MqttPublisher
from kerotrack.pubsub.bus import PubSubBus
from kerotrack.scheduler.jobs import run_job
from kerotrack.scheduler.service import SchedulerService
from kerotrack.settings.seeds import seed_defaults
from kerotrack.settings.service import SettingsService


class _DormantClient:
    """No-op MQTT publisher used until the operator wires a real broker."""

    async def publish(self, topic: str, payload, *, qos: int = 0, retain: bool = False):
        return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    boot = get_bootstrap()
    engine = init_engine(boot.database_url)
    await ensure_schema(engine)
    sf = session_factory(engine)
    async with sf() as session:
        await seed_defaults(session)
    settings_service = SettingsService(sf)
    pubsub = PubSubBus()
    publisher = MqttPublisher(client=_DormantClient())
    feed = MqttFeedRing()

    async def _runner(name: str):
        return await run_job(name, app_state=app.state)

    scheduler = SchedulerService(
        settings_service=settings_service, runner=_runner, timezone=boot.tz
    )

    app.state.bootstrap = boot
    app.state.engine = engine
    app.state.session_factory = sf
    app.state.settings_service = settings_service
    app.state.pubsub = pubsub
    app.state.publisher = publisher
    app.state.scheduler = scheduler
    app.state.mqtt_feed = feed
    app.state.secret_key = boot.app_secret_key

    await scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="KeroTrack v2", version="0.0.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(settings_router)
    app.include_router(status_router)
    app.include_router(readings_router)
    app.include_router(analysis_router)
    app.include_router(costs_router)
    app.include_router(refills_router)
    app.include_router(hdd_router)
    app.include_router(mqtt_feed_router)
    app.include_router(stream_router)
    app.include_router(admin_router)

    boot = get_bootstrap()
    secret_key = boot.require_secret()

    # Reverse-add — runtime order Session → RequireAuth → CSRF.
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
