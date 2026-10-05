"""Nest heating storage: daily ingest, monthly roll-up, CSV import (synthetic data)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.ingest.nest import (
    MIN_DAILY_ROWS_FOR_MONTH,
    handle_nest_payload,
    import_nest_months,
    load_nest_monthly,
    parse_nest_months_csv,
    parse_nest_payload,
    store_nest_daily,
)
from kerotrack.models.nest_heating_daily import NestHeatingDaily
from kerotrack.models.nest_heating_monthly import NestHeatingMonthly

pytestmark = pytest.mark.asyncio


async def _monthly(sf: async_sessionmaker) -> dict[str, tuple[float, str]]:
    async with sf() as session:
        rows = (await session.execute(select(NestHeatingMonthly))).scalars().all()
    return {r.month: (r.heating_hours, r.source) for r in rows}


async def test_parse_payload_valid() -> None:
    from datetime import date

    assert parse_nest_payload({"date": "2026-01-05", "heating_hours": 1.25}) == (
        date(2026, 1, 5),
        1.25,
    )
    assert parse_nest_payload({"date": "2026-01-05", "heating_hours": 0}) == (date(2026, 1, 5), 0.0)
    assert parse_nest_payload({"date": "2026-01-05", "heating_hours": "2.5"}) == (
        date(2026, 1, 5),
        2.5,
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"date": "2026-13-01", "heating_hours": 1.0},
        {"date": "05/01/2026", "heating_hours": 1.0},
        {"date": "2026-01-05", "heating_hours": -0.1},
        {"date": "2026-01-05", "heating_hours": 24.5},
        {"date": "2026-01-05", "heating_hours": "lots"},
        {"date": "2026-01-05", "heating_hours": float("nan")},
        {"date": "2026-01-05", "heating_hours": True},
        {"date": "2026-01-05"},
        {"heating_hours": 1.0},
        {"date": 20260105, "heating_hours": 1.0},
        ["not", "a", "dict"],
    ],
)
async def test_parse_payload_rejects_invalid(raw) -> None:
    assert parse_nest_payload(raw) is None


async def test_handle_payload_upserts_daily_row(sf: async_sessionmaker) -> None:
    assert await handle_nest_payload({"date": "2026-01-05", "heating_hours": 1.5}, sf=sf)
    assert await handle_nest_payload({"date": "2026-01-05", "heating_hours": 2.0}, sf=sf)
    async with sf() as session:
        rows = (await session.execute(select(NestHeatingDaily))).scalars().all()
    assert len(rows) == 1
    assert rows[0].date == "2026-01-05"
    assert rows[0].heating_hours == pytest.approx(2.0)
    assert rows[0].received_at


async def test_handle_invalid_payload_warns_without_echo(
    sf: async_sessionmaker, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="kerotrack.ingest.nest")
    assert not await handle_nest_payload({"date": "2026-01-05", "heating_hours": 31.75}, sf=sf)
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert "31.75" not in caplog.text
    async with sf() as session:
        assert (await session.execute(select(NestHeatingDaily))).scalars().all() == []


async def test_monthly_rollup_needs_25_days(sf: async_sessionmaker) -> None:
    assert MIN_DAILY_ROWS_FOR_MONTH == 25
    for day in range(1, 25):
        await store_nest_daily(sf, f"2026-01-{day:02d}", 2.0)
    assert await _monthly(sf) == {}
    await store_nest_daily(sf, "2026-01-25", 2.0)
    hours, source = (await _monthly(sf))["2026-01"]
    assert source == "daily"
    # 25 days of 2 h scaled to the month's 31 days.
    assert hours == pytest.approx(50.0 * 31 / 25)
    for day in range(26, 32):
        await store_nest_daily(sf, f"2026-01-{day:02d}", 2.0)
    assert (await _monthly(sf))["2026-01"][0] == pytest.approx(62.0)


async def test_monthly_rollup_never_overwrites_report(sf: async_sessionmaker) -> None:
    await import_nest_months(sf, [("2026-01", 40.0, "report"), ("2026-02", 30.0, "prev")])
    for day in range(1, 32):
        await store_nest_daily(sf, f"2026-01-{day:02d}", 2.0)
    for day in range(1, 29):
        await store_nest_daily(sf, f"2026-02-{day:02d}", 1.0)
    monthly = await _monthly(sf)
    assert monthly["2026-01"] == (40.0, "report")
    assert monthly["2026-02"] == (pytest.approx(28.0), "daily")


async def test_csv_import_and_load(sf: async_sessionmaker, tmp_path: Path) -> None:
    csv_path = tmp_path / "nest.csv"
    csv_path.write_text(
        "month,heating_hours,source\n2025-01,60.5,report\n2025-02,41,prev\n\n",
        encoding="utf-8",
    )
    rows = parse_nest_months_csv(csv_path)
    assert rows == [("2025-01", 60.5, "report"), ("2025-02", 41.0, "prev")]
    assert await import_nest_months(sf, rows) == (2, 0)
    # Re-import overwrites in place.
    assert await import_nest_months(sf, [("2025-01", 61.0, "report")]) == (1, 0)
    assert await load_nest_monthly(sf) == {"2025-01": 61.0, "2025-02": 41.0}


@pytest.mark.parametrize(
    "body",
    [
        "month,heating_hours\n2025-01,60\n",  # missing column
        "month,heating_hours,source\n2025-13,60,report\n",
        "month,heating_hours,source\n2025-01,-1,report\n",
        "month,heating_hours,source\n2025-01,800,report\n",
        "month,heating_hours,source\n2025-01,60,guess\n",
        "month,heating_hours,source\n2025-01,abc,report\n",
    ],
)
async def test_csv_import_rejects_bad_rows(tmp_path: Path, body: str) -> None:
    csv_path = tmp_path / "nest.csv"
    csv_path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        parse_nest_months_csv(csv_path)


async def test_import_report_beats_prev_within_a_file(sf: async_sessionmaker) -> None:
    rows = [
        ("2025-01", 60.0, "prev"),
        ("2025-01", 62.0, "report"),  # report replaces the earlier prev
        ("2025-01", 99.0, "prev"),  # never beats the report
        ("2025-02", 40.0, "report"),
        ("2025-02", 41.0, "report"),  # same source duplicate: first wins
        ("2025-03", 30.0, "prev"),
        ("2025-03", 31.0, "daily"),  # neither is a report: first wins
    ]
    assert await import_nest_months(sf, rows) == (3, 4)
    monthly = await _monthly(sf)
    assert monthly == {
        "2025-01": (62.0, "report"),
        "2025-02": (40.0, "report"),
        "2025-03": (30.0, "prev"),
    }


async def test_import_never_replaces_stored_report_with_prev(sf: async_sessionmaker) -> None:
    await import_nest_months(sf, [("2025-01", 62.0, "report"), ("2025-02", 40.0, "prev")])
    imported, skipped = await import_nest_months(
        sf,
        [("2025-01", 70.0, "prev"), ("2025-02", 44.0, "prev"), ("2025-03", 5.0, "report")],
    )
    assert (imported, skipped) == (2, 1)
    monthly = await _monthly(sf)
    assert monthly["2025-01"] == (62.0, "report")
    assert monthly["2025-02"] == (44.0, "prev")
    # A report does replace a stored prev.
    assert await import_nest_months(sf, [("2025-02", 45.0, "report")]) == (1, 0)
    assert (await _monthly(sf))["2025-02"] == (45.0, "report")
