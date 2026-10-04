"""Provider registry and polling."""

from __future__ import annotations

import re

import httpx

from kerotrack.quotes.homefuelsdirect import HomeFuelsDirect
from kerotrack.quotes.models import PollResult, QuoteRequest

PROVIDERS: dict[str, object] = {"homefuelsdirect": HomeFuelsDirect()}


_QUERY = re.compile(r"\?[^\s'\"]*")


def _err(e: Exception) -> str:
    """Error text for storage; URL query strings (which carry the postcode) are scrubbed."""
    return type(e).__name__ + ": " + _QUERY.sub("?<redacted>", str(e))[:120]


async def poll(client: httpx.AsyncClient, req: QuoteRequest, names: list[str]) -> list[PollResult]:
    """Poll each named provider once, retrying once on failure."""
    results: list[PollResult] = []
    for name in names:
        provider = PROVIDERS.get(name)
        if provider is None:
            results.append(PollResult(name, [], "unknown provider"))
            continue
        error: str | None = None
        options = []
        for _attempt in range(2):
            try:
                options = await provider.fetch(client, req)  # type: ignore[attr-defined]
                error = None if options else "no prices"
                break
            except Exception as e:  # noqa: BLE001 - any provider failure is recorded, not raised
                error = _err(e)
        results.append(PollResult(name, options, error))
    return results
