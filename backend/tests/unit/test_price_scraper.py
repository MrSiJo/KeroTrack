"""Price scraper retry, parser, cache fallback (mocked via respx)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from kerotrack.prices.cache import PriceCache
from kerotrack.prices.scraper import (
    YOURNRG_API_PATH,
    fetch_boilerjuice,
    fetch_current_price,
    fetch_yournrg,
)


pytestmark = pytest.mark.asyncio


BJ_URL = "https://www.boilerjuice.com/heating-oil-prices-england/"
YN_URL = "https://yournrg.co.uk/domestic/heating-oil-prices"
YN_API = "https://yournrg.co.uk" + YOURNRG_API_PATH


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


def _yn_payload(ppl_500: float = 104.52, ppl_750: float = 104.33, ppl_1000: float = 105.18):
    return [
        {"Litres": 500, "AveragePrice": ppl_500, "YesterdayClose": ppl_500 - 0.1},
        {"Litres": 750, "AveragePrice": ppl_750, "YesterdayClose": ppl_750 - 0.1},
        {"Litres": 1000, "AveragePrice": ppl_1000, "YesterdayClose": ppl_1000 - 0.1},
        {"Litres": 2000, "AveragePrice": ppl_1000 - 0.3, "YesterdayClose": ppl_1000 - 0.4},
    ]


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


# -------------------------------------------------------- YourNRG parsing


@respx.mock
async def test_fetch_yournrg_parses_500_750_1000() -> None:
    respx.get(YN_API).respond(json=_yn_payload(104.52, 104.33, 105.18))
    async with httpx.AsyncClient() as client:
        result = await fetch_yournrg(client, YN_URL)
    assert result is not None
    assert result.ppl_500l == 104.52
    assert result.ppl_750l == 104.33
    assert result.ppl_1000l == 105.18


@respx.mock
async def test_fetch_yournrg_returns_none_on_unexpected_payload() -> None:
    respx.get(YN_API).respond(json={"oops": True})
    async with httpx.AsyncClient() as client:
        assert await fetch_yournrg(client, YN_URL) is None


@respx.mock
async def test_fetch_yournrg_returns_none_when_litres_missing() -> None:
    # Only a 2000 L entry — no headline 500/750/1000.
    respx.get(YN_API).respond(json=[{"Litres": 2000, "AveragePrice": 99.0}])
    async with httpx.AsyncClient() as client:
        assert await fetch_yournrg(client, YN_URL) is None


# -------------------------------------------------------- combined fetch


@respx.mock
async def test_fetch_current_price_uses_boilerjuice_first(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "cache.json", ttl_seconds=60)
    respx.get(BJ_URL).respond(content=_bj_html(106.95).encode())
    respx.get(YN_API).respond(json=_yn_payload())
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client,
            cache=cache,
            boilerjuice_url=BJ_URL,
            yournrg_url=YN_URL,
            retries=1,
            retry_delay=0.0,
        )
    assert result.ppl == 106.95
    assert result.source == "boilerjuice"
    assert result.used_cache is False
    saved = json.loads(cache.path.read_text())
    assert saved["ppl"] == 106.95
    assert saved["yournrg"]["ppl_500l"] == 104.52


@respx.mock
async def test_fetch_current_price_falls_back_to_yournrg(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "cache.json", ttl_seconds=60)
    respx.get(BJ_URL).respond(status_code=503)
    respx.get(YN_API).respond(json=_yn_payload(104.52, 104.33, 105.18))
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client,
            cache=cache,
            boilerjuice_url=BJ_URL,
            yournrg_url=YN_URL,
            retries=1,
            retry_delay=0.0,
        )
    assert result.ppl == 104.52
    assert result.source == "yournrg"


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
    respx.get(YN_API).respond(status_code=503)
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client,
            cache=cache,
            boilerjuice_url=BJ_URL,
            yournrg_url=YN_URL,
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
            yournrg_url=YN_URL,
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
    respx.get(YN_API).respond(json=_yn_payload())
    async with httpx.AsyncClient() as client:
        result = await fetch_current_price(
            client=client,
            cache=cache,
            boilerjuice_url=BJ_URL,
            yournrg_url=YN_URL,
            retries=2,
            retry_delay=0.0,
        )
    assert result.ppl == 79.0
    assert route.call_count == 2
