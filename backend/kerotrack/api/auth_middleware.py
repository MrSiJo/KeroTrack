"""RequireAuth middleware (ADR-0005, JobTrack pattern)."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

EXEMPT_PATHS = frozenset(
    {
        "/api/health",
        "/api/setup/status",
        "/api/setup",
        "/api/auth/login",
        "/api/auth/logout",
    }
)


def _unauth() -> JSONResponse:
    return JSONResponse(
        {"error": "auth_required", "message": "Authentication required"},
        status_code=401,
    )


class RequireAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        path = request.url.path
        if path.startswith("/api/") and path not in EXEMPT_PATHS:
            if not request.session.get("username"):
                return _unauth()
        return await call_next(request)
