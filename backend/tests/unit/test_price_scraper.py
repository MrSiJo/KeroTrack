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
)


pytestmark = pytest.mark.asyncio


BJ_URL = "https://www.boilerjuice.com/heating-oil-prices-england/"


def _bj_html(ppl: float = 78.5) -> str:
    """Realistic BoilerJuice page — multiple font-weight-bold spans, only one
    contains the price string. The previous parser grabbed the first match
    (the logo) and missed the real price."""
    return f"""
    <html><body>
      <span class="font-weight-bold">Tomorrow's energy, today</span>
      <span class="font-weight-semi-bold">unrelated</span>
      <h5>Today's average price for 1000 litres of heating oil:
        <span class="font-weight-bold">{ppl} pence per litre</span>
      </h5>
    </body></html>
    """


# -------------------------------------------------------- BoilerJuice parsing


@respx.mock
async def test_fetch_boilerjuice_walks_past_unrelated_bold_spans() -> None:
    respx.get(BJ_URL).respond(content=_bj_html(106.95).encode())
    async with httpx.AsyncClient() as client:
        ppl = await fetch_boilerjuice(client, BJ_URL)
    assert ppl == 106.95


@respx.mock
async def test_fetch_boilerjuice_returns_none_when_layout_changes() -> None:
    respx.get(BJ_URL).respond(content=b"<html><body><p>nothing here</p></body></html>")
    async with httpx.AsyncClient() as client:
        ppl = await fetch_boilerjuice(client, BJ_URL)
    assert ppl is None


@respx.mock
async def test_fetch_boilerjuice_rejects_implausible_value() -> None:
    # A '0' or absurd value shouldn't be accepted as a real ppl.
    html = b"""<html><body>
      <span class="font-weight-bold">0 pence per litre</span>
    </body></html>"""
    respx.get(BJ_URL).respond(content=html)
    async with httpx.AsyncClient() as client:
        ppl = await fetch_boilerjuice(client, BJ_URL)
    assert ppl is None


# -------------------------------------------------------- combined fetch


@respx.mock
async def test_fetch_current_price_scrapes_boilerjuice(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "cache.json", ttl_seconds=60)
    respx.get(BJ_URL).respond(content=_bj_html(106.95).encode())
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client,
            cache=cache,
            boilerjuice_url=BJ_URL,
            retries=1,
            retry_delay=0.0,
        )
    assert result.ppl == 106.95
    assert result.source == "boilerjuice"
    assert result.used_cache is False
    saved = json.loads(cache.path.read_text())
    assert saved["ppl"] == 106.95
    assert saved["source"] == "boilerjuice"
    assert saved["boilerjuice"] == {"ppl": 106.95, "ok": True}
    assert "yournrg" not in saved


@respx.mock
async def test_fetch_current_price_total_failure_without_cache(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "cache.json", ttl_seconds=60)
    respx.get(BJ_URL).respond(status_code=503)
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client,
            cache=cache,
            boilerjuice_url=BJ_URL,
            retries=1,
            retry_delay=0.0,
        )
    assert result.ppl is None
    assert result.fetch_failed is True


@respx.mock
async def test_fetch_current_price_uses_stale_cache_on_total_failure(
    tmp_path: Path,
) -> None:
    cache = PriceCache(tmp_path / "cache.json", ttl_seconds=1)
    cache.save(
        {
            "fetched_at": "2020-01-01T00:00:00",
            "ppl": 65.0,
            "source": "boilerjuice",
        }
    )
    respx.get(BJ_URL).respond(status_code=503)
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client,
            cache=cache,
            boilerjuice_url=BJ_URL,
            retries=2,
            retry_delay=0.0,
        )
    assert result.ppl == 65.0
    assert result.used_cache is True


@respx.mock
async def test_fresh_cache_short_circuits(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "cache.json", ttl_seconds=86400)
    from datetime import datetime, timezone
    cache.save(
        {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "ppl": 73.0,
            "source": "boilerjuice",
            "boilerjuice": {"ppl": 73.0, "ok": True},
        }
    )
    # No mocks installed — would error if called.
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client,
            cache=cache,
            boilerjuice_url=BJ_URL,
            retries=1,
            retry_delay=0.0,
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
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client,
            cache=cache,
            boilerjuice_url=BJ_URL,
            retries=2,
            retry_delay=0.0,
        )
    assert result.ppl == 79.0
    assert route.call_count == 2
