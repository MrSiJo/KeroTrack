"""Async SQLAlchemy engine factory and session helpers.

Phase 1 ships the minimum needed by the settings service. Phase 2 expands
this with the WAL pragma, schema bootstrap, and lifespan integration.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def init_engine(database_url: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine for `database_url`.

    For SQLite URLs we register a `connect` listener that turns on WAL mode and
    reasonable pragmas — Phase 2 puts the same pragmas in front of every
    connection in the lifespan helper, but we set them here too so unit tests
    that build their own engines get the same behaviour.
    """
    engine = create_async_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
    )

    if database_url.startswith("sqlite"):
        sync_engine = engine.sync_engine

        @event.listens_for(sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield an async session; commit on success, roll back on error."""
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
