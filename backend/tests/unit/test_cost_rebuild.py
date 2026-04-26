"""ONS importer + PPL resolver + rebuild-costs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.cost_rebuild import (
    PplResolver,
    _interpolate,
    _is_sensor_stuck,
    import_ons_csv,
    parse_ons_csv,
    rebuild_periods,
)
from kerotrack.models.monthly_ppl import MonthlyPpl
from kerotrack.models.reading import Reading
from kerotrack.models.refill import ActualRefillCost
from kerotrack.models.refill_period import RefillPeriod


pytestmark = pytest.mark.asyncio


ONS_FIXTURE = '''"Title","RPI: Ave price - Heating oil"
"CDID","KJ5U"
"Important notes",
"2023","73463"
"2024","64836"
"2023 Q1","81620"
"2024 Q4","60012"
"2024 OCT","60868"
"2024 NOV","58941"
"2024 DEC","60227"
"2025 JAN","65301"
'''


async def test_parse_ons_csv_keeps_only_monthly_rows(tmp_path: Path) -> None:
    p = tmp_path / "ons.csv"
    p.write_text(ONS_FIXTURE)
    rows = parse_ons_csv(p)
    months = dict(rows)
    assert "2024-10" in months
    assert "2024-11" in months
    assert "2024-12" in months
    assert "2025-01" in months
    # Annual + quarterly rows must be skipped.
    assert "2023" not in months
    assert "2023-Q1" not in months
    # Conversion: 60868 / 1000 = 60.868 p/L
    assert months["2024-10"] == pytest.approx(60.868, abs=0.001)
    assert months["2025-01"] == pytest.approx(65.301, abs=0.001)


async def test_parse_ons_csv_missing_file_returns_empty(tmp_path: Path) -> None:
    assert parse_ons_csv(tmp_path / "missing.csv") == []


async def test_import_ons_csv_upserts_idempotently(
    sf: async_sessionmaker, tmp_path: Path
) -> None:
    p = tmp_path / "ons.csv"
    p.write_text(ONS_FIXTURE)
    first = await import_ons_csv(sf, csv_path=p)
    second = await import_ons_csv(sf, csv_path=p)
    assert first == 4
    assert second == 4
    async with sf() as session:
        rows = (await session.execute(select(MonthlyPpl))).scalars().all()
    assert len(rows) == 4


async def test_is_sensor_stuck_true_when_window_has_one_value() -> None:
    readings = [
        Reading(
            date=f"2025-08-{i:02d} 12:00:00",
            id="probe",
            current_ppl=51.99,
            litres_remaining=900 - i,
        )
        for i in range(1, 30)
    ]
    target = datetime(2025, 8, 15, 12, 0)
    assert _is_sensor_stuck(readings, target) is True


async def test_is_sensor_stuck_false_when_window_changes() -> None:
    readings = [
        Reading(
            date=f"2026-01-{i:02d} 12:00:00",
            id="probe",
            current_ppl=55.5 + (i * 0.05),
            litres_remaining=900 - i,
        )
        for i in range(1, 25)
    ]
    target = datetime(2026, 1, 12, 12, 0)
    assert _is_sensor_stuck(readings, target) is False


async def test_interpolate_returns_anchor_value_outside_range() -> None:
    anchors = [
        (datetime(2025, 1, 15), 65.30),
        (datetime(2026, 4, 26), 106.95),
    ]
    # Before earliest → first anchor's value.
    assert _interpolate(datetime(2024, 1, 1), anchors) == pytest.approx(65.30)
    # After latest → last anchor's value.
    assert _interpolate(datetime(2027, 1, 1), anchors) == pytest.approx(106.95)
    # Midpoint → halfway between (66 weeks ÷ 2).
    midpoint = _interpolate(datetime(2025, 8, 21), anchors)
    assert 80.0 < midpoint < 90.0  # rough midway value


async def test_resolver_prefers_live_sensor_when_changing() -> None:
    resolver = PplResolver(ons={}, actuals=[], first_reliable=None)
    window = [
        Reading(
            date=f"2026-04-{i:02d} 12:00:00",
            id="p",
            current_ppl=100.0 + i * 0.5,
            litres_remaining=500,
        )
        for i in range(1, 20)
    ]
    ppl, src = resolver.resolve(
        target_dt=datetime(2026, 4, 10, 12, 0),
        sensor_ppl=104.5,
        sensor_window=window,
    )
    assert src == "sensor_live"
    assert ppl == pytest.approx(104.5)


async def test_resolver_uses_ons_when_sensor_stuck() -> None:
    resolver = PplResolver(
        ons={"2025-08": 62.0},
        actuals=[],
        first_reliable=None,
    )
    window = [
        Reading(
            date=f"2025-08-{i:02d} 12:00:00",
            id="p",
            current_ppl=51.99,
            litres_remaining=500,
        )
        for i in range(1, 30)
    ]
    ppl, src = resolver.resolve(
        target_dt=datetime(2025, 8, 15, 12, 0),
        sensor_ppl=51.99,
        sensor_window=window,
    )
    assert src == "ons_month"
    assert ppl == pytest.approx(62.0)


async def test_resolver_interpolates_in_ons_gap() -> None:
    resolver = PplResolver(
        ons={"2025-01": 65.30},
        actuals=[
            ActualRefillCost(
                refill_date="2025-05-07 12:00:00",
                actual_volume_litres=1100,
                actual_ppl=56.79,
                total_cost=586.32,
            ),
        ],
        first_reliable=(datetime(2026, 4, 26, 7, 32), 106.95),
    )
    # No sensor data, fall through to interpolation.
    window: list[Reading] = []
    ppl, src = resolver.resolve(
        target_dt=datetime(2025, 9, 1, 12, 0),
        sensor_ppl=None,
        sensor_window=window,
    )
    assert src == "interpolated"
    # Should be between the May refill (56.79) and Apr 2026 reliable (106.95).
    assert 56.0 < ppl < 107.0


async def test_rebuild_periods_dry_run_does_not_mutate(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """Without --apply, the existing rows are preserved."""
    async with sf() as session:
        # Seed a spurious migrated period and a sensor refill pair.
        session.add(
            RefillPeriod(
                start_date="2025-04-25 10:03:43",
                end_date="2025-12-01 06:18:02",
                days=219,
                total_consumption=230.0,
                total_cost=117.27,
                refill_ppl=50.99,
                used_actual_cost=0,
            )
        )
        await session.commit()

    report = await rebuild_periods(sf, seeded_settings, apply=False)
    async with sf() as session:
        kept = (await session.execute(select(RefillPeriod))).scalars().all()
    assert len(kept) == 1  # untouched
    assert report["apply"] is False
    assert report["spurious_period_count"] == 1


async def test_rebuild_periods_apply_clears_spurious_and_writes_real(
    sf: async_sessionmaker, seeded_settings
) -> None:
    async with sf() as session:
        # Spurious migrated rows.
        for end in ("2025-12-01 06:18:02", "2026-01-01 06:18:02"):
            session.add(
                RefillPeriod(
                    start_date="2025-04-25 10:03:43",
                    end_date=end,
                    days=219,
                    total_consumption=230.0,
                    total_cost=117.27,
                    refill_ppl=50.99,
                    used_actual_cost=0,
                )
            )
        # Two real refill events with consumption between them.
        session.add(
            Reading(
                date="2025-04-25 10:00:00",
                id="probe",
                litres_remaining=1100.0,
                current_ppl=51.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        # 11 daily readings between the two refills (April 26 → May 6).
        for i in range(1, 12):
            session.add(
                Reading(
                    date=f"2025-04-{25 + i:02d} 12:00:00"
                    if 25 + i <= 30
                    else f"2025-05-{(25 + i) - 30:02d} 12:00:00",
                    id="probe",
                    litres_remaining=1100.0 - i * 10.0,
                    current_ppl=51.0,  # all stuck on purpose
                    refill_detected="n",
                    leak_detected="n",
                )
            )
        session.add(
            Reading(
                date="2025-05-07 12:00:00",
                id="probe",
                litres_remaining=1200.0,
                current_ppl=56.79,
                refill_detected="y",
                leak_detected="n",
            )
        )
        await session.commit()

    report = await rebuild_periods(sf, seeded_settings, apply=True)
    async with sf() as session:
        rows = (
            (await session.execute(select(RefillPeriod).order_by(RefillPeriod.end_date)))
            .scalars()
            .all()
        )
    # Spurious rows gone; one real period present.
    assert all(r.end_date != "2025-12-01 06:18:02" for r in rows)
    assert all(r.end_date != "2026-01-01 06:18:02" for r in rows)
    assert any(r.end_date == "2025-05-07 12:00:00" for r in rows)
    assert report["apply"] is True
    assert report["spurious_period_count"] == 2
