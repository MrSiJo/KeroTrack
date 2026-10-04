"""Async price scraper for the BoilerJuice national index.

Retry, stale-cache fallback when the scrape fails. The scraper makes no
direct settings calls — the caller passes URLs + cache. This keeps the unit
under test free of DB plumbing.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx
from bs4 import BeautifulSoup

from kerotrack.prices.cache import PriceCache

logger = logging.getLogger(__name__)


PRICE_FETCH_RETRIES = 3
PRICE_FETCH_RETRY_DELAY_S = 1.0  # tests speed this up by patching

@dataclass(frozen=True, slots=True)
class PriceFetchResult:
    ppl: float | None
    source: str | None
    boilerjuice_ppl: float | None
    used_cache: bool
    # True when a scrape was attempted and every provider failed (regardless
    # of whether a stale cache value papered over it). Lets PriceService
    # apply a cooldown instead of re-running the full retry ladder on every
    # ingest reading (KERO-M3). False on fresh-cache short-circuits.
    fetch_failed: bool = False


async def fetch_boilerjuice(
    client: httpx.AsyncClient, url: str
) -> float | None:
    """Scrape the BoilerJuice 'England average' price.

    The page sets the figure inside a `font-weight-bold` span — but that
    class is reused throughout the layout (logo, etc). Walk every match
    and pick the one that contains 'pence per litre'.
    """
    response = await client.get(
        url, timeout=10.0, headers={"User-Agent": "Mozilla/5.0"}
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    for span in soup.find_all("span", class_="font-weight-bold"):
        text = span.get_text(" ", strip=True)
        if "pence per litre" not in text.lower() and "per litre" not in text.lower():
            continue
        token = text.split()[0].rstrip("p").rstrip(",")
        try:
            value = float(token)
        except ValueError:
            continue
        if 30.0 <= value <= 500.0:  # sanity-bound a real ppl
            return value
    return None


async def _retry(
    fetch: Callable[[], Awaitable[object | None]],
    name: str,
    *,
    retries: int = PRICE_FETCH_RETRIES,
    delay: float = PRICE_FETCH_RETRY_DELAY_S,
) -> object | None:
    for attempt in range(retries):
        try:
            result = await fetch()
            if result is not None:
                return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s attempt %s/%s failed: %s", name, attempt + 1, retries, exc)
        if attempt < retries - 1:
            await asyncio.sleep(delay)
    return None


async def fetch_current_price(
    *,
    client: httpx.AsyncClient,
    cache: PriceCache,
    boilerjuice_url: str,
    retries: int = PRICE_FETCH_RETRIES,
    retry_delay: float = PRICE_FETCH_RETRY_DELAY_S,
) -> PriceFetchResult:
    """Scrape BoilerJuice and update the cache.

    Cache hits short-circuit when the cached `fetched_at` is within
    `ttl_seconds` of now. On total failure return the stale cached price (if
    any) with `used_cache=True`.
    """
    cached = cache.load()
    if cache.is_fresh(cached):
        return PriceFetchResult(
            ppl=float(cached["ppl"]) if cached and cached.get("ppl") is not None else None,
            source=cached.get("source"),
            boilerjuice_ppl=cached.get("boilerjuice", {}).get("ppl"),
            used_cache=True,
        )

    bj = await _retry(
        lambda: fetch_boilerjuice(client, boilerjuice_url),
        "boilerjuice",
        retries=retries,
        delay=retry_delay,
    )
    bj_ppl: float | None = bj if isinstance(bj, (int, float)) else None

    ppl: float | None
    source: str | None
    if bj_ppl is not None:
        ppl, source = bj_ppl, "boilerjuice"
    else:
        ppl, source = None, None

    if ppl is not None:
        cache.save(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "ppl": ppl,
                "source": source,
                "boilerjuice": {"ppl": bj_ppl, "ok": bj_ppl is not None},
            }
        )
        return PriceFetchResult(
            ppl=ppl,
            source=source,
            boilerjuice_ppl=bj_ppl,
            used_cache=False,
        )

    if cached and cached.get("ppl") is not None:
        return PriceFetchResult(
            ppl=float(cached["ppl"]),
            source=cached.get("source"),
            boilerjuice_ppl=cached.get("boilerjuice", {}).get("ppl"),
            used_cache=True,
            fetch_failed=True,
        )
    return PriceFetchResult(
        ppl=None,
        source=None,
        boilerjuice_ppl=None,
        used_cache=False,
        fetch_failed=True,
    )
