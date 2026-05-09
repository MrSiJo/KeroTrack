"""Per-IP rate limiter for auth-sensitive endpoints.

slowapi attaches itself to FastAPI via `app.state.limiter` plus a global
exception handler. Routes opt in with `@limiter.limit(...)`.

`get_remote_address` reads the client IP from the request. When deployed
behind nginx-proxy-manager the real client IP arrives in `X-Forwarded-For`;
slowapi will use it if Starlette's `proxy_headers` are honoured, which is
the default with `uvicorn[standard]`.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
