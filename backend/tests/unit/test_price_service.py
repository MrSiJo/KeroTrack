"""PriceService failure cooldown (KERO-M3) — a dead-provider scrape must
not re-run the full retry ladder on every ingest reading."""

from __future__ import annotations

from pathlib import Path

import pytest

import kerotrack.prices.service as price_service_mod
from kerotrack.prices.scraper import PriceFetchResult
from kerotrack.prices.service import PriceService

pytestmark = pytest.mark.asyncio


def _failed() -> PriceFetchResult:
    return PriceFetchResult(
        ppl=None,
        source=None,
        boilerjuice_ppl=None,
        yournrg=None,
        used_cache=False,
        fetch_failed=True,
    )


def _ok(ppl: float) -> PriceFetchResult:
    return PriceFetchResult(
        ppl=ppl,
        source="boilerjuice",
        boilerjuice_ppl=ppl,
        yournrg=None,
        used_cache=False,
    )


async def test_failed_scrape_enters_cooldown(
    sf, seeded_settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    async def fake_fetch(**kwargs) -> PriceFetchResult:
        nonlocal calls
        calls += 1
        return _failed()

    monkeypatch.setattr(price_service_mod, "fetch_current_price", fake_fetch)
    svc = PriceService(
        settings_service=seeded_settings, cache_path=tmp_path / "cache.json"
    )

    assert await svc.current_ppl() is None
    assert await svc.current_ppl() is None  # within cooldown — no re-scrape
    assert calls == 1


async def test_cooldown_expires_and_success_clears_it(
    sf, seeded_settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    async def fake_fetch(**kwargs) -> PriceFetchResult:
        nonlocal calls
        calls += 1
        return _failed() if calls == 1 else _ok(78.5)

    monkeypatch.setattr(price_service_mod, "fetch_current_price", fake_fetch)
    svc = PriceService(
        settings_service=seeded_settings, cache_path=tmp_path / "cache.json"
    )

    assert await svc.current_ppl() is None
    # Age the failure past the cooldown window.
    svc._failed_at -= price_service_mod.FAILURE_COOLDOWN_S + 1
    assert await svc.current_ppl() == 78.5
    assert calls == 2
    # A successful scrape clears the cooldown — next call fetches again.
    assert await svc.current_ppl() == 78.5
    assert calls == 3
