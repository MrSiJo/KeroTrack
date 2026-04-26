"""Async price scraper for BoilerJuice + YourNRG.

Per-source retry, stale-cache fallback when both fail. The scraper makes no
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

# YourNRG injects prices via JS; the page calls this Umbraco surface that
# returns a JSON array keyed on litres ordered.
YOURNRG_API_PATH = "/Umbraco/Surface/InformationPageSurface/GetCurrentAveragePrices"


@dataclass(frozen=True, slots=True)
class YourNrgResult:
    ppl_500l: float
    ppl_750l: float
    ppl_1000l: float


@dataclass(frozen=True, slots=True)
class PriceFetchResult:
    ppl: float | None
    source: str | None
    boilerjuice_ppl: float | None
    yournrg: YourNrgResult | None
    used_cache: bool


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


def _yournrg_origin(url: str) -> str:
    """Derive the API origin from the configured page URL."""
    if "://" not in url:
        return f"https://{url}"
    scheme, _, rest = url.partition("://")
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}"


async def fetch_yournrg(
    client: httpx.AsyncClient, page_url: str
) -> YourNrgResult | None:
    """Hit YourNRG's GetCurrentAveragePrices Umbraco surface.

    Returns the 500/750/1000-litre averages. The 500 L price is the headline
    we feed into recalc as `current_ppl` (matches v1's fallback semantics).
    """
    origin = _yournrg_origin(page_url)
    api_url = origin + YOURNRG_API_PATH
    response = await client.get(
        api_url,
        timeout=10.0,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": page_url,
        },
    )
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    by_litres: dict[int, float] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        litres = entry.get("Litres")
        price = entry.get("AveragePrice")
        if isinstance(litres, int) and isinstance(price, (int, float)):
            by_litres[litres] = float(price)
    try:
        return YourNrgResult(
            ppl_500l=by_litres[500],
            ppl_750l=by_litres[750],
            ppl_1000l=by_litres[1000],
        )
    except KeyError:
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
    yournrg_url: str,
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
            yournrg=None,
            used_cache=True,
        )

    bj = await _retry(
        lambda: fetch_boilerjuice(client, boilerjuice_url),
        "boilerjuice",
        retries=retries,
        delay=retry_delay,
    )
    yn = await _retry(
        lambda: fetch_yournrg(client, yournrg_url),
        "yournrg",
        retries=retries,
        delay=retry_delay,
    )
    bj_ppl: float | None = bj if isinstance(bj, (int, float)) else None
    yn_result: YourNrgResult | None = yn if isinstance(yn, YourNrgResult) else None

    ppl: float | None
    source: str | None
    if bj_ppl is not None:
        ppl, source = bj_ppl, "boilerjuice"
    elif yn_result is not None:
        ppl, source = yn_result.ppl_500l, "yournrg"
    else:
        ppl, source = None, None

    if ppl is not None:
        cache.save(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "ppl": ppl,
                "source": source,
                "boilerjuice": {"ppl": bj_ppl, "ok": bj_ppl is not None},
                "yournrg": {
                    "ppl_500l": yn_result.ppl_500l if yn_result else None,
                    "ppl_750l": yn_result.ppl_750l if yn_result else None,
                    "ppl_1000l": yn_result.ppl_1000l if yn_result else None,
                    "ok": yn_result is not None,
                },
            }
        )
        return PriceFetchResult(
            ppl=ppl,
            source=source,
            boilerjuice_ppl=bj_ppl,
            yournrg=yn_result,
            used_cache=False,
        )

    if cached and cached.get("ppl") is not None:
        return PriceFetchResult(
            ppl=float(cached["ppl"]),
            source=cached.get("source"),
            boilerjuice_ppl=cached.get("boilerjuice", {}).get("ppl"),
            yournrg=None,
            used_cache=True,
        )
    return PriceFetchResult(
        ppl=None,
        source=None,
        boilerjuice_ppl=None,
        yournrg=None,
        used_cache=False,
    )
