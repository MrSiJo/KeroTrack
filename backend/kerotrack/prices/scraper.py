"""Async price scraper for BoilerJuice + HomeFuelsDirect.

Per-source retry, stale-cache fallback when both fail. The scraper makes no
direct settings calls — the caller passes URLs + cache. This keeps the unit
under test free of DB plumbing.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable

import httpx
from bs4 import BeautifulSoup

from kerotrack.prices.cache import PriceCache

logger = logging.getLogger(__name__)


PRICE_FETCH_RETRIES = 3
PRICE_FETCH_RETRY_DELAY_S = 1.0  # tests speed this up by patching


@dataclass(frozen=True, slots=True)
class HomeFuelsResult:
    ppl_500l: float
    ppl_900l: float


@dataclass(frozen=True, slots=True)
class PriceFetchResult:
    ppl: float | None
    source: str | None
    boilerjuice_ppl: float | None
    homefuelsdirect: HomeFuelsResult | None
    used_cache: bool


async def fetch_boilerjuice(
    client: httpx.AsyncClient, url: str
) -> float | None:
    response = await client.get(
        url, timeout=10.0, headers={"User-Agent": "Mozilla/5.0"}
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    span = soup.find("span", class_="font-weight-bold")
    if span is None:
        return None
    text = span.get_text(strip=True)
    if "pence per litre" not in text.lower():
        # Some BoilerJuice templates split the words; tolerate both.
        if "per litre" not in text.lower():
            return None
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return None


async def fetch_homefuelsdirect(
    client: httpx.AsyncClient, url: str
) -> HomeFuelsResult | None:
    response = await client.get(url, timeout=10.0)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    table = soup.find("table", id="county-table")
    if table is None:
        return None
    rows = table.find_all("tr")
    if len(rows) < 2:
        return None
    cells = rows[1].find_all("td", class_="trPrice")
    if len(cells) < 2:
        return None
    try:
        return HomeFuelsResult(
            ppl_500l=float(cells[0].get_text().split()[0]),
            ppl_900l=float(cells[1].get_text().split()[0]),
        )
    except (ValueError, IndexError):
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
    homefuelsdirect_url: str,
    retries: int = PRICE_FETCH_RETRIES,
    retry_delay: float = PRICE_FETCH_RETRY_DELAY_S,
) -> PriceFetchResult:
    """Run both scrapers and update the cache.

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
            homefuelsdirect=None,
            used_cache=True,
        )

    bj = await _retry(
        lambda: fetch_boilerjuice(client, boilerjuice_url),
        "boilerjuice",
        retries=retries,
        delay=retry_delay,
    )
    hfd = await _retry(
        lambda: fetch_homefuelsdirect(client, homefuelsdirect_url),
        "homefuelsdirect",
        retries=retries,
        delay=retry_delay,
    )
    bj_ppl: float | None = bj if isinstance(bj, (int, float)) else None
    hfd_result: HomeFuelsResult | None = hfd if isinstance(hfd, HomeFuelsResult) else None

    ppl: float | None
    source: str | None
    if bj_ppl is not None:
        ppl, source = bj_ppl, "boilerjuice"
    elif hfd_result is not None:
        ppl, source = hfd_result.ppl_500l, "homefuelsdirect"
    else:
        ppl, source = None, None

    if ppl is not None:
        cache.save(
            {
                "fetched_at": datetime.utcnow().isoformat(),
                "ppl": ppl,
                "source": source,
                "boilerjuice": {"ppl": bj_ppl, "ok": bj_ppl is not None},
                "homefuelsdirect": {
                    "ppl_500l": hfd_result.ppl_500l if hfd_result else None,
                    "ppl_900l": hfd_result.ppl_900l if hfd_result else None,
                    "ok": hfd_result is not None,
                },
            }
        )
        return PriceFetchResult(
            ppl=ppl,
            source=source,
            boilerjuice_ppl=bj_ppl,
            homefuelsdirect=hfd_result,
            used_cache=False,
        )

    # Total failure — fall back to stale cache if we have one.
    if cached and cached.get("ppl") is not None:
        return PriceFetchResult(
            ppl=float(cached["ppl"]),
            source=cached.get("source"),
            boilerjuice_ppl=cached.get("boilerjuice", {}).get("ppl"),
            homefuelsdirect=None,
            used_cache=True,
        )
    return PriceFetchResult(
        ppl=None,
        source=None,
        boilerjuice_ppl=None,
        homefuelsdirect=None,
        used_cache=False,
    )
