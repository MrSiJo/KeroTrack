"""Auth service unit tests — single-user bootstrap, lookup, password change."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.services.auth_service import (
    AuthError,
    authenticate,
    bootstrap_user,
    change_password,
    get_user,
    is_setup_complete,
)


pytestmark = pytest.mark.asyncio


async def test_setup_status_empty(sf: async_sessionmaker) -> None:
    async with sf() as session:
        assert await is_setup_complete(session) is False


async def test_bootstrap_user_creates_single_user(sf: async_sessionmaker) -> None:
    async with sf() as session:
        user = await bootstrap_user(session, "admin", "hunter2-strong-pw")
    assert user.username == "admin"
    async with sf() as session:
        assert await is_setup_complete(session) is True


async def test_bootstrap_user_rejects_second(sf: async_sessionmaker) -> None:
    async with sf() as session:
        await bootstrap_user(session, "admin", "hunter2-strong-pw")
    async with sf() as session:
        with pytest.raises(AuthError) as ei:
            await bootstrap_user(session, "second", "anything-long-enough")
    assert ei.value.code == "already_setup"
    assert ei.value.status == 409


async def test_authenticate_round_trip(sf: async_sessionmaker) -> None:
    async with sf() as session:
        await bootstrap_user(session, "admin", "hunter2-strong-pw")
    async with sf() as session:
        user = await authenticate(session, "admin", "hunter2-strong-pw")
    assert user.username == "admin"


async def test_authenticate_wrong_password(sf: async_sessionmaker) -> None:
    async with sf() as session:
        await bootstrap_user(session, "admin", "hunter2-strong-pw")
    async with sf() as session:
        with pytest.raises(AuthError) as ei:
            await authenticate(session, "admin", "nope")
    assert ei.value.code == "auth_required"


async def test_authenticate_unknown_user(sf: async_sessionmaker) -> None:
    async with sf() as session:
        await bootstrap_user(session, "admin", "hunter2-strong-pw")
    async with sf() as session:
        with pytest.raises(AuthError):
            await authenticate(session, "ghost", "hunter2-strong-pw")


async def test_change_password_rotates_credential(sf: async_sessionmaker) -> None:
    async with sf() as session:
        await bootstrap_user(session, "admin", "old-password-1")
    async with sf() as session:
        await change_password(
            session, "admin", "old-password-1", "new-password-2"
        )
    async with sf() as session:
        with pytest.raises(AuthError):
            await authenticate(session, "admin", "old-password-1")
        user = await authenticate(session, "admin", "new-password-2")
    assert user.username == "admin"


async def test_change_password_rejects_wrong_old(sf: async_sessionmaker) -> None:
    async with sf() as session:
        await bootstrap_user(session, "admin", "old-password-1")
    async with sf() as session:
        with pytest.raises(AuthError) as ei:
            await change_password(
                session, "admin", "wrong", "new-password-2"
            )
    assert ei.value.code == "invalid_password"


async def test_bootstrap_user_rejects_short_password(sf: async_sessionmaker) -> None:
    async with sf() as session:
        with pytest.raises(AuthError) as ei:
            await bootstrap_user(session, "admin", "short")
    assert ei.value.code == "weak_password"


async def test_change_password_rejects_short_new(sf: async_sessionmaker) -> None:
    async with sf() as session:
        await bootstrap_user(session, "admin", "old-password-1")
    async with sf() as session:
        with pytest.raises(AuthError) as ei:
            await change_password(session, "admin", "old-password-1", "short")
    assert ei.value.code == "weak_password"
