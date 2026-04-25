"""Shared pytest fixtures for the KeroTrack v2 backend test suite."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from kerotrack.db import init_engine, session_factory
from kerotrack.db_migrate import ensure_schema
from kerotrack.settings.seeds import seed_defaults
from kerotrack.settings.service import SettingsService


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "kerotrack-test.db"


@pytest.fixture
def database_url(tmp_db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_db_path.as_posix()}"


@pytest_asyncio.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = init_engine(database_url)
    await ensure_schema(eng)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker:
    return session_factory(engine)


@pytest_asyncio.fixture
async def seeded_settings(sf: async_sessionmaker) -> SettingsService:
    async with sf() as session:
        await seed_defaults(session)
    return SettingsService(sf)


@pytest.fixture
def temp_app_secret_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = "0" * 64
    monkeypatch.setenv("APP_SECRET_KEY", key)
    return key
