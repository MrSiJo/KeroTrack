"""Quote store: save_poll / save_index / best_recent / history, and
PriceService preferring the cheapest local quote."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from kerotrack.prices.service import PriceService
from kerotrack.quotes import store
from kerotrack.quotes.models import PollResult, QuoteOption, effective_ppl

pytestmark = pytest.mark.asyncio

BJ_URL = "https://www.boilerjuice.com/heating-oil-prices-england/"
NOW = datetime(2026, 10, 4, 12, 0, 0)


def _opt(total: float, *, urgent: bool = False, supplier: str = "homefuelsdirect",
         label: str = "Window1") -> QuoteOption:
    return QuoteOption(
        supplier=supplier, litres=500, delivery_by=None, delivery_label=label,
        urgent=urgent, ppl_net=total / 1.05 / 500, total_inc_vat=total,
        fees_inc_vat=0.0,
    )


def _ts(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")


async def test_save_poll_writes_option_and_failure_rows(sf) -> None:
    n = await store.save_poll(
        sf, _ts(1), 500,
        [PollResult("a", options=[_opt(400.0), _opt(450.0, urgent=True)]),
         PollResult("b", error="boom")],
    )
    assert n == 3
    rows = await store.latest_poll(sf)
    assert len(rows) == 3
    ok = [r for r in rows if r.ok]
    assert len(ok) == 2
    assert ok[0].ppl_effective == pytest.approx(effective_ppl(400.0, 500)) or ok[1].ppl_effective == pytest.approx(effective_ppl(400.0, 500))
    bad = [r for r in rows if not r.ok]
    assert bad[0].supplier == "b" and bad[0].error == "boom"
    assert bad[0].kind == "quote" and bad[0].litres == 500


async def test_best_recent_picks_cheapest_non_urgent(sf) -> None:
    await store.save_poll(
        sf, _ts(2), 500,
        [PollResult("a", options=[_opt(430.0), _opt(300.0, urgent=True)]),
         PollResult("b", options=[_opt(410.0, supplier="b")]),
         PollResult("c", error="down")],
    )
    best = await store.best_recent(sf, now=NOW)
    assert best is not None
    assert best.supplier == "b"
    assert best.ppl_effective == pytest.approx(effective_ppl(410.0, 500))


async def test_best_recent_excludes_stale_and_index(sf) -> None:
    await store.save_poll(sf, _ts(40), 500, [PollResult("a", options=[_opt(300.0)])])
    await store.save_index(sf, _ts(1), 70.0, "boilerjuice")
    assert await store.best_recent(sf, now=NOW) is None
    assert await store.best_recent(sf, now=NOW, max_age_h=48) is not None


async def test_best_recent_none_when_only_failures(sf) -> None:
    await store.save_poll(sf, _ts(1), 500, [PollResult("a", error="x")])
    assert await store.best_recent(sf, now=NOW) is None


async def test_latest_poll_newest_only_and_index_excluded(sf) -> None:
    await store.save_poll(sf, _ts(30), 500, [PollResult("a", options=[_opt(400.0)])])
    await store.save_poll(sf, _ts(5), 500, [PollResult("a", options=[_opt(420.0)])])
    await store.save_index(sf, _ts(1), 71.5, "boilerjuice")
    rows = await store.latest_poll(sf)
    assert [r.fetched_at for r in rows] == [_ts(5)]


async def test_save_index_and_history(sf) -> None:
    await store.save_index(sf, _ts(3), 71.5, "boilerjuice")
    await store.save_index(sf, _ts(2), None, "boilerjuice")
    await store.save_index(sf, _ts(100), 60.0, "boilerjuice")
    rows = await store.history(sf, since=NOW - timedelta(days=1))
    assert [r.fetched_at for r in rows] == [_ts(3), _ts(2)]
    assert rows[0].kind == "index" and rows[0].ok == 1 and rows[0].ppl_effective == 71.5
    assert rows[1].ok == 0 and rows[1].ppl_effective is None


async def test_current_ppl_prefers_quote_lookup(
    sf, seeded_settings, tmp_path: Path
) -> None:
    async def lookup() -> float | None:
        return 88.8

    svc = PriceService(
        settings_service=seeded_settings, cache_path=tmp_path / "c.json",
        quote_lookup=lookup,
    )
    # No BoilerJuice mock installed: would error if scraped.
    assert await svc.current_ppl() == 88.8


@respx.mock
async def test_current_ppl_falls_back_when_lookup_none(
    sf, seeded_settings, tmp_path: Path
) -> None:
    async def lookup() -> float | None:
        return None

    respx.get(BJ_URL).respond(content=(
        b'<html><body><span class="font-weight-bold">79.5 pence per litre</span>'
        b"</body></html>"))
    svc = PriceService(
        settings_service=seeded_settings, cache_path=tmp_path / "c.json",
        quote_lookup=lookup,
    )
    assert await svc.current_ppl() == 79.5
