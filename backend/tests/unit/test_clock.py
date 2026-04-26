"""Clock helpers — tz-aware now and DST-correct parsing."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from kerotrack.clock import local_now, local_now_str, parse_local


@pytest.fixture(autouse=True)
def _bootstrap_tz_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Europe/London")
    monkeypatch.setenv("APP_SECRET_KEY", "0" * 64)
    from kerotrack.bootstrap import reset_bootstrap_cache

    reset_bootstrap_cache()
    yield
    reset_bootstrap_cache()


def test_local_now_is_in_configured_zone() -> None:
    n = local_now()
    assert n.tzinfo is not None
    # The zone should be Europe/London — UTC offset will be +0 in winter,
    # +1 in summer.
    assert n.utcoffset() in {ZoneInfo("Europe/London").utcoffset(n)}


def test_local_now_str_is_naive_yyyy_mm_dd_hh_mm_ss() -> None:
    s = local_now_str()
    assert len(s) == 19
    assert s[4] == "-" and s[7] == "-" and s[10] == " "
    # Round-trip parses without raising.
    datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def test_parse_local_attaches_zone() -> None:
    dt = parse_local("2026-04-26 08:00:00")
    assert dt is not None
    assert dt.tzinfo is not None
    # In April London is BST (+01:00).
    assert dt.utcoffset().total_seconds() == 3600


def test_parse_local_winter_is_gmt() -> None:
    dt = parse_local("2026-01-15 08:00:00")
    assert dt is not None
    assert dt.utcoffset().total_seconds() == 0


def test_parse_local_round_trip_against_local_now() -> None:
    s = local_now_str()
    dt = parse_local(s)
    assert dt is not None
    diff = abs((local_now() - dt).total_seconds())
    assert diff < 5  # within a few seconds


def test_parse_local_returns_none_for_garbage() -> None:
    assert parse_local("not a date") is None
    assert parse_local("") is None
    assert parse_local(None) is None


def test_parse_local_explicit_tz_override() -> None:
    dt = parse_local("2026-04-26 08:00:00", tz="UTC")
    assert dt is not None
    assert dt.utcoffset().total_seconds() == 0


def test_dst_boundary_parses_consistently() -> None:
    # 2026 BST starts 2026-03-29 01:00 UTC. Compare an April reading
    # against a January reading: the wall-clock difference should match
    # the calendar difference within an hour (the DST step itself).
    summer = parse_local("2026-04-26 08:00:00")
    winter = parse_local("2026-01-26 08:00:00")
    assert summer and winter
    delta_days = (summer - winter).total_seconds() / 86400
    assert 89.9 < delta_days < 90.1  # ~90 calendar days, BST gives 89 23h
