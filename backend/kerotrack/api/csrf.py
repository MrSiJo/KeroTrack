"""CSRF middleware on mutating verbs — see ADR-0005."""

from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_EXEMPT_PATHS = frozenset(
    {
        "/api/setup",
        "/api/auth/login",
    }
)


def generate_csrf_token() -> str:
    return secrets.token_hex(32)


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        path = request.url.path
        if (
            request.method in MUTATING_METHODS
            and path.startswith("/api/")
            and path not in CSRF_EXEMPT_PATHS
            and request.session.get("username")
        ):
            expected = request.session.get("csrf_token")
            provided = request.headers.get("X-CSRF-Token")
            if not provided or provided != expected:
                return JSONResponse(
                    {
                        "error": "csrf_missing",
                        "message": "CSRF token missing or invalid",
                    },
                    status_code=403,
                )
        return await call_next(request)
