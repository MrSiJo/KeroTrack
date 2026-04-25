"""Price scraper retry, parser, cache fallback (mocked via respx)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from kerotrack.prices.cache import PriceCache
from kerotrack.prices.scraper import (
    fetch_boilerjuice,
    fetch_current_price,
    fetch_homefuelsdirect,
)


pytestmark = pytest.mark.asyncio


BJ_URL = "https://www.boilerjuice.com/heating-oil-prices-england/"
HFD_URL = "https://homefuelsdirect.co.uk/home/heating-oil-prices/dorset"


def _bj_html(ppl: float = 78.5) -> str:
    return f"""
    <html><body>
      <span class="font-weight-bold">{ppl} pence per litre</span>
    </body></html>
    """


def _hfd_html(ppl_500: float = 80.5, ppl_900: float = 78.0) -> str:
    return f"""
    <html><body>
      <table id="county-table">
        <tr><th>x</th></tr>
        <tr>
          <td class="trPrice">{ppl_500} ppl</td>
          <td class="trPrice">{ppl_900} ppl</td>
        </tr>
      </table>
    </body></html>
    """


@respx.mock
async def test_fetch_boilerjuice_parses_price() -> None:
    respx.get(BJ_URL).respond(content=_bj_html(81.5).encode())
    async with httpx.AsyncClient() as client:
        ppl = await fetch_boilerjuice(client, BJ_URL)
    assert ppl == 81.5


@respx.mock
async def test_fetch_homefuelsdirect_parses_table() -> None:
    respx.get(HFD_URL).respond(content=_hfd_html(80.0, 78.5).encode())
    async with httpx.AsyncClient() as client:
        result = await fetch_homefuelsdirect(client, HFD_URL)
    assert result is not None
    assert result.ppl_500l == 80.0
    assert result.ppl_900l == 78.5


@respx.mock
async def test_fetch_current_price_uses_boilerjuice_first(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "cache.json", ttl_seconds=60)
    respx.get(BJ_URL).respond(content=_bj_html(78.0).encode())
    respx.get(HFD_URL).respond(content=_hfd_html().encode())
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client,
            cache=cache,
            boilerjuice_url=BJ_URL,
            homefuelsdirect_url=HFD_URL,
            retries=1,
            retry_delay=0.0,
        )
    assert result.ppl == 78.0
    assert result.source == "boilerjuice"
    assert result.used_cache is False
    assert cache.path.exists()
    saved = json.loads(cache.path.read_text())
    assert saved["ppl"] == 78.0
    assert saved["source"] == "boilerjuice"


@respx.mock
async def test_fetch_current_price_falls_back_to_hfd(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "cache.json", ttl_seconds=60)
    respx.get(BJ_URL).respond(status_code=503)
    respx.get(HFD_URL).respond(content=_hfd_html(80.0, 78.5).encode())
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client, cache=cache,
            boilerjuice_url=BJ_URL, homefuelsdirect_url=HFD_URL,
            retries=1, retry_delay=0.0,
        )
    assert result.ppl == 80.0
    assert result.source == "homefuelsdirect"


@respx.mock
async def test_fetch_current_price_uses_stale_cache_on_total_failure(
    tmp_path: Path,
) -> None:
    # Pre-populate a stale cache.
    cache = PriceCache(tmp_path / "cache.json", ttl_seconds=1)
    cache.save(
        {
            "fetched_at": "2020-01-01T00:00:00",
            "ppl": 65.0,
            "source": "boilerjuice",
        }
    )
    respx.get(BJ_URL).respond(status_code=503)
    respx.get(HFD_URL).respond(status_code=503)
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client, cache=cache,
            boilerjuice_url=BJ_URL, homefuelsdirect_url=HFD_URL,
            retries=2, retry_delay=0.0,
        )
    assert result.ppl == 65.0
    assert result.used_cache is True


@respx.mock
async def test_fresh_cache_short_circuits(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "cache.json", ttl_seconds=86400)
    from datetime import datetime
    cache.save(
        {
            "fetched_at": datetime.utcnow().isoformat(),
            "ppl": 73.0,
            "source": "boilerjuice",
            "boilerjuice": {"ppl": 73.0, "ok": True},
        }
    )
    # No mocks installed — would error if called.
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client, cache=cache,
            boilerjuice_url=BJ_URL, homefuelsdirect_url=HFD_URL,
            retries=1, retry_delay=0.0,
        )
    assert result.ppl == 73.0
    assert result.used_cache is True


@respx.mock
async def test_retry_succeeds_on_second_attempt(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "cache.json", ttl_seconds=60)
    route = respx.get(BJ_URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, content=_bj_html(79.0)),
        ]
    )
    respx.get(HFD_URL).respond(content=_hfd_html().encode())
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client, cache=cache,
            boilerjuice_url=BJ_URL, homefuelsdirect_url=HFD_URL,
            retries=2, retry_delay=0.0,
        )
    assert result.ppl == 79.0
    assert route.call_count == 2
