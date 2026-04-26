"""PriceService — async wrapper over scraper + cache used by ingest + the API.

Holds a long-lived httpx.AsyncClient. The cache lives on disk so the value
survives container restarts. `current_ppl()` returns the latest known
price (cached or freshly scraped), or None if no source has ever succeeded.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from kerotrack.prices.cache import PriceCache
from kerotrack.prices.scraper import PriceFetchResult, fetch_current_price
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)


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

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def refresh(self) -> PriceFetchResult:
        ttl = int(await self._svc.get("prices.cache_ttl_seconds"))
        cache = PriceCache(self._cache_path, ttl_seconds=ttl)
        bj_url = str(await self._svc.get("prices.boilerjuice_url"))
        hfd_url = str(await self._svc.get("prices.homefuelsdirect_url"))
        client = await self._ensure_client()
        try:
            result = await fetch_current_price(
                client=client,
                cache=cache,
                boilerjuice_url=bj_url,
                homefuelsdirect_url=hfd_url,
            )
        except Exception:  # noqa: BLE001
            logger.exception("price fetch failed")
            cached = cache.load()
            ppl = cached.get("ppl") if cached else None
            result = PriceFetchResult(
                ppl=float(ppl) if ppl is not None else None,
                source=cached.get("source") if cached else None,
                boilerjuice_ppl=None,
                homefuelsdirect=None,
                used_cache=cached is not None,
            )
        self._last = result
        return result

    async def current_ppl(self) -> float | None:
        result = await self.refresh()
        return result.ppl

    @property
    def last(self) -> PriceFetchResult | None:
        return self._last
