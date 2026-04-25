"""Auth domain service — single-user bootstrap, lookup, password rotation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kerotrack.models.user import User
from kerotrack.security.crypto import hash_password, verify_password


class AuthError(Exception):
    """Carries a machine-readable code and HTTP status hint."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


async def is_setup_complete(session: AsyncSession) -> bool:
    row = (await session.execute(select(User.id).limit(1))).scalar_one_or_none()
    return row is not None


async def bootstrap_user(
    session: AsyncSession, username: str, password: str
) -> User:
    if not username or not username.strip():
        raise AuthError("invalid_username", "username is required", 400)
    if not password:
        raise AuthError("invalid_password", "password is required", 400)
    if await is_setup_complete(session):
        raise AuthError("already_setup", "Application is already configured", 409)
    user = User(
        username=username.strip(), password_hash=hash_password(password)
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user(session: AsyncSession, username: str) -> User | None:
    return (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()


async def authenticate(
    session: AsyncSession, username: str, password: str
) -> User:
    user = await get_user(session, username)
    if user is None or not verify_password(password, user.password_hash):
        raise AuthError("auth_required", "Invalid username or password", 401)
    return user


async def change_password(
    session: AsyncSession, username: str, old_password: str, new_password: str
) -> None:
    user = await get_user(session, username)
    if user is None or not verify_password(old_password, user.password_hash):
        raise AuthError("invalid_password", "Wrong current password", 400)
    if not new_password:
        raise AuthError("invalid_password", "new password is required", 400)
    user.password_hash = hash_password(new_password)
    await session.commit()
