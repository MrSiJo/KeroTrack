"""Auth + setup routes per ADR-0005."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from kerotrack.api.csrf import generate_csrf_token
from kerotrack.api.rate_limit import limiter
from kerotrack.services.auth_service import (
    AuthError,
    authenticate,
    bootstrap_user,
    change_password,
    is_setup_complete,
)

router = APIRouter()


class SetupBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=12, max_length=512)


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=512)


class ChangePasswordBody(BaseModel):
    old_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=12, max_length=512)


def _raise_auth(exc: AuthError) -> None:
    raise HTTPException(
        status_code=exc.status,
        detail={"error": exc.code, "message": str(exc)},
    )


@router.get("/api/setup/status")
async def setup_status(request: Request) -> dict[str, bool]:
    sf = request.app.state.session_factory
    async with sf() as session:
        complete = await is_setup_complete(session)
    return {"needs_setup": not complete}


@router.post("/api/setup")
@limiter.limit("5/minute")
async def setup(body: SetupBody, request: Request) -> dict[str, str]:
    sf = request.app.state.session_factory
    try:
        async with sf() as session:
            user = await bootstrap_user(session, body.username, body.password)
    except AuthError as exc:
        _raise_auth(exc)
    return {"username": user.username}


@router.post("/api/auth/login")
@limiter.limit("5/minute")
async def login(body: LoginBody, request: Request) -> dict[str, str]:
    sf = request.app.state.session_factory
    try:
        async with sf() as session:
            user = await authenticate(session, body.username, body.password)
    except AuthError as exc:
        _raise_auth(exc)
    token = generate_csrf_token()
    request.session["username"] = user.username
    request.session["csrf_token"] = token
    return {"username": user.username, "csrf_token": token}


@router.get("/api/auth/me")
async def me(request: Request) -> dict[str, str]:
    username = request.session.get("username")
    if not username:
        raise HTTPException(
            status_code=401,
            detail={"error": "auth_required", "message": "Not authenticated"},
        )
    token = request.session.get("csrf_token")
    if not token:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
    return {"username": username, "csrf_token": token}


@router.post("/api/auth/logout")
async def logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}


@router.post("/api/auth/change-password")
@limiter.limit("5/minute")
async def post_change_password(
    body: ChangePasswordBody, request: Request
) -> dict[str, bool]:
    username = request.session.get("username")
    if not username:
        raise HTTPException(
            status_code=401,
            detail={"error": "auth_required", "message": "Not authenticated"},
        )
    sf = request.app.state.session_factory
    try:
        async with sf() as session:
            await change_password(
                session, username, body.old_password, body.new_password
            )
    except AuthError as exc:
        _raise_auth(exc)
    return {"ok": True}
