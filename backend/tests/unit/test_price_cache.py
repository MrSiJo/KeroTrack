"""PriceCache unit tests — load/save/freshness."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kerotrack.prices.cache import PriceCache


def test_load_returns_none_when_missing(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "missing.json")
    assert cache.load() is None


def test_save_then_load_round_trip(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "c.json")
    cache.save({"ppl": 78.5, "source": "boilerjuice"})
    loaded = cache.load()
    assert loaded == {"ppl": 78.5, "source": "boilerjuice"}


def test_is_fresh_within_ttl(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "c.json", ttl_seconds=60)
    payload = {"fetched_at": datetime.now(timezone.utc).isoformat(), "ppl": 80.0}
    assert cache.is_fresh(payload) is True


def test_is_fresh_outside_ttl(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "c.json", ttl_seconds=60)
    payload = {
        "fetched_at": (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(),
        "ppl": 80.0,
    }
    assert cache.is_fresh(payload) is False


def test_is_fresh_handles_malformed_timestamp(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "c.json")
    assert cache.is_fresh({"fetched_at": "not-a-date"}) is False
    assert cache.is_fresh(None) is False
    assert cache.is_fresh({}) is False


def test_load_handles_corrupt_json(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text("not json")
    cache = PriceCache(p)
    assert cache.load() is None
