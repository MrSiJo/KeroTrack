"""Per-IP rate limiter for auth-sensitive endpoints.

slowapi attaches itself to FastAPI via `app.state.limiter` plus a global
exception handler. Routes opt in with `@limiter.limit(...)`.

`get_remote_address` reads the client IP the ASGI server hands us. uvicorn
only substitutes the `X-Forwarded-For` value when the immediate peer is in
`forwarded_allow_ips`, which defaults to `127.0.0.1` — and in the compose
deployment the peer is the frontend nginx container, so by default the XFF
header set by nginx is IGNORED and every client shares one bucket keyed on
the nginx container IP. To key per client, set `FORWARDED_ALLOW_IPS` in the
deploy host's `.env` to the frontend container's IP (or the compose
network's subnet, CIDR) — see the `environment` note in `compose.yaml`.
Keep it narrow: the backend port is also published on the host, so a wide
trust range would let direct callers spoof XFF to rotate buckets.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
