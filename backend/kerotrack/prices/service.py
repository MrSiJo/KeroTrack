"""PriceService — async wrapper over scraper + cache used by ingest + the API.

Holds a long-lived httpx.AsyncClient. The cache lives on disk so the value
survives container restarts. `current_ppl()` returns the latest known
price (cached or freshly scraped), or None if no source has ever succeeded.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from kerotrack.prices.cache import PriceCache
from kerotrack.prices.scraper import PriceFetchResult, fetch_current_price
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)


# After a scrape where every provider failed, don't re-run the full
# retry ladder (2 sources × 3 attempts × 1s delays, ~6s inline in the
# ingest path) for this long — serve the last known result instead
# (KERO-M3). Total failure never writes a cache entry, so without this
# the stall repeats on every reading until a provider recovers.
FAILURE_COOLDOWN_S = 900.0


class PriceService:
    def __init__(
        self,
        *,
        settings_service: SettingsService,
        cache_path: Path,
    ) -> None:
        self._svc = settings_service
        self._cache_path = cache_path
        self._client: httpx.AsyncClient | None = None
        self._last: PriceFetchResult | None = None
        self._failed_at: float | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def refresh(self) -> PriceFetchResult:
        if (
            self._failed_at is not None
            and self._last is not None
            and (time.monotonic() - self._failed_at) < FAILURE_COOLDOWN_S
        ):
            return self._last
        ttl = int(await self._svc.get("prices.cache_ttl_seconds"))
        cache = PriceCache(self._cache_path, ttl_seconds=ttl)
        bj_url = str(await self._svc.get("prices.boilerjuice_url"))
        yn_url = str(await self._svc.get("prices.yournrg_url"))
        client = await self._ensure_client()
        try:
            result = await fetch_current_price(
                client=client,
                cache=cache,
                boilerjuice_url=bj_url,
                yournrg_url=yn_url,
            )
        except Exception:  # noqa: BLE001
            logger.exception("price fetch failed")
            cached = cache.load()
            ppl = cached.get("ppl") if cached else None
            result = PriceFetchResult(
                ppl=float(ppl) if ppl is not None else None,
                source=cached.get("source") if cached else None,
                boilerjuice_ppl=None,
                yournrg=None,
                used_cache=cached is not None,
                fetch_failed=True,
            )
        self._failed_at = time.monotonic() if result.fetch_failed else None
        self._last = result
        return result

    async def current_ppl(self) -> float | None:
        result = await self.refresh()
        return result.ppl

    @property
    def last(self) -> PriceFetchResult | None:
        return self._last
