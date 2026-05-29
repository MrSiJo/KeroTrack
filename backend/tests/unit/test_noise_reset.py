"""Tests for the one-shot historical noise-flag reset.

`reset_noise_flags` walks the readings table in order, recomputes the
same sanity bound that the live ingest uses, and clears
``refill_detected`` / ``leak_detected`` flags on rows where the delta
between adjacent in-cadence readings exceeds the bound. Dry-run mode
reports without mutating; ``apply=True`` persists changes.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from kerotrack.analysis.noise_reset import reset_noise_flags
from kerotrack.db_migrate import ensure_schema
from kerotrack.models.reading import Reading
from kerotrack.settings.seeds import seed_defaults
from kerotrack.settings.service import SettingsService


@pytest_asyncio.fixture
async def sf():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await ensure_schema(engine)
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with sf() as session:
        await seed_defaults(session)
    try:
        yield sf
    finally:
        await engine.dispose()


def _r(when: datetime, *, air_gap_cm: float, litres: float,
       refill: str = "n", leak: str = "n", raw_flags: str = "144") -> Reading:
    return Reading(
        date=when.strftime("%Y-%m-%d %H:%M:%S"),
        id="12345",
        temperature=20.0,
        litres_remaining=litres,
        litres_used_since_last=0.0,
        percentage_remaining=round(litres / 1225.0 * 100.0, 1),
        oil_depth_cm=round(137.0 - air_gap_cm, 1),
        air_gap_cm=air_gap_cm,
        current_ppl=78.5,
        cost_used="0.00",
        cost_to_fill="0.00",
        heating_degree_days=0.0,
        seasonal_efficiency=0.99,
        refill_detected=refill,
        leak_detected=leak,
        raw_flags=raw_flags,
        litres_to_order=round(1225.0 - litres, 1),
        bars_remaining=5,
    )


async def _seed(sf, readings: list[Reading]) -> None:
    async with sf() as session:
        for r in readings:
            session.add(r)
        await session.commit()


@pytest.mark.asyncio
async def test_resets_implausible_short_interval_y_flags(sf) -> None:
    # Classic May 2026 multipath oscillation pattern: 30 min interval,
    # ~180 L jump in each direction. Both should be reset.
    t0 = datetime(2026, 5, 24, 12, 0, 0)
    await _seed(sf, [
        _r(t0, air_gap_cm=80.0, litres=520.0),
        _r(t0 + timedelta(minutes=30), air_gap_cm=100.0, litres=329.0, leak="y"),
        _r(t0 + timedelta(minutes=60), air_gap_cm=80.0, litres=520.0, refill="y"),
    ])
    svc = SettingsService(sf)

    report = await reset_noise_flags(sf, svc, apply=True)

    assert report["reset_count"] == 2
    async with sf() as session:
        rows = (await session.execute(select(Reading).order_by(Reading.date))).scalars().all()
    assert all(r.refill_detected == "n" for r in rows)
    assert all(r.leak_detected == "n" for r in rows)
    # The noisy 100 cm row is sentinel-stamped — its litres/air_gap don't
    # represent reality and downstream walkers must skip it.
    assert "noise_suppressed" in (rows[1].raw_flags or "")
    # The third row's raw values match the trusted baseline (back at 80 cm,
    # 520 L) — the 'refill_detected=y' was a spurious "return to truth"
    # flag. Its flag is cleared but the row stays as honest data.
    assert "noise_suppressed" not in (rows[2].raw_flags or "")
    # Unaffected baseline row stays untouched.
    assert "noise_suppressed" not in (rows[0].raw_flags or "")


@pytest.mark.asyncio
async def test_preserves_legitimate_long_interval_refill(sf) -> None:
    # 21 h gap between readings — outside the sanity-bound window. A
    # genuine refill recorded as 'y' must survive the cleanup.
    t0 = datetime(2026, 5, 1, 12, 0, 0)
    await _seed(sf, [
        _r(t0, air_gap_cm=110.0, litres=200.0),
        _r(t0 + timedelta(hours=21), air_gap_cm=20.0, litres=1040.0, refill="y"),
    ])
    svc = SettingsService(sf)

    report = await reset_noise_flags(sf, svc, apply=True)

    assert report["reset_count"] == 0
    async with sf() as session:
        rows = (await session.execute(select(Reading).order_by(Reading.date))).scalars().all()
    assert rows[1].refill_detected == "y"


@pytest.mark.asyncio
async def test_resets_drop_when_gap_exceeds_max_but_baseline_alive(sf) -> None:
    # The May 29 2026 phantom: two missed broadcasts put the gap to the
    # previous row at 1.5 h (> SANITY_BOUND_MAX_GAP_HOURS). The old gate
    # reset the baseline and left the leak flag untouched. A *drop* can't
    # beat the consumption budget at any gap, so the cleaner must still
    # mark it. (Contrast test_preserves_legitimate_long_interval_refill —
    # a long-gap RISE is still trusted as a real delivery.)
    t0 = datetime(2026, 5, 29, 7, 40, 16)
    await _seed(sf, [
        _r(t0, air_gap_cm=80.0, litres=510.5),
        _r(t0 + timedelta(minutes=90), air_gap_cm=93.0, litres=393.7, leak="y"),
    ])
    svc = SettingsService(sf)

    await reset_noise_flags(sf, svc, apply=True)

    async with sf() as session:
        rows = (await session.execute(select(Reading).order_by(Reading.date))).scalars().all()
    assert rows[1].leak_detected == "n"
    assert "noise_suppressed" in (rows[1].raw_flags or "")


@pytest.mark.asyncio
async def test_chains_through_noise_to_last_trusted_baseline(sf) -> None:
    """The Watchman Sonic can lock onto a wrong reflection for several
    readings in a row. Consecutive readings at the same wrong value have
    a small per-pair delta, so the bound never trips on the chain itself.
    Reset must compare each reading against the last NON-noise baseline,
    not the immediately previous row, so the whole chain gets marked.
    """
    t0 = datetime(2026, 5, 28, 14, 0, 0)
    await _seed(sf, [
        _r(t0, air_gap_cm=80.0, litres=520.0),
        _r(t0 + timedelta(minutes=30), air_gap_cm=93.0, litres=391.0, leak="y"),
        # Chain — already flagged 'n' but at the wrong value. Per-pair
        # delta from 93→93 is tiny, but vs. trusted 80 baseline it's huge.
        _r(t0 + timedelta(minutes=60), air_gap_cm=93.0, litres=391.0),
        _r(t0 + timedelta(minutes=90), air_gap_cm=93.0, litres=391.0),
        _r(t0 + timedelta(minutes=120), air_gap_cm=80.0, litres=520.0),
    ])
    svc = SettingsService(sf)

    await reset_noise_flags(sf, svc, apply=True)

    async with sf() as session:
        rows = (await session.execute(select(Reading).order_by(Reading.date))).scalars().all()
    # The 3 noisy 93-cm rows should all carry the sentinel, regardless of
    # whether their original flag was 'y' or 'n'.
    chain = [r for r in rows if r.air_gap_cm == 93.0]
    assert len(chain) == 3
    assert all("noise_suppressed" in (r.raw_flags or "") for r in chain), \
        [(r.date, r.raw_flags) for r in chain]


@pytest.mark.asyncio
async def test_apply_deletes_orphan_refill_periods(sf) -> None:
    """Refill period rows whose end_date no longer maps to a 'y' anchor
    (because the noise-cleanup reset it) should be removed — except when
    the operator has curated them with an invoice or notes."""
    from kerotrack.models.refill_period import RefillPeriod

    t0 = datetime(2026, 5, 22, 13, 9, 26)
    t1 = t0 + timedelta(minutes=30)
    t2 = t1 + timedelta(minutes=30)
    await _seed(sf, [
        # The pair that was 'y' on both ends — both get cleared.
        _r(t0 - timedelta(minutes=30), air_gap_cm=80.0, litres=520.0),
        _r(t0, air_gap_cm=100.0, litres=329.0, leak="y"),
        _r(t1, air_gap_cm=80.0, litres=520.0, refill="y"),
    ])
    async with sf() as session:
        # An orphan: end_date refers to the noisy refill (will be reset).
        session.add(RefillPeriod(
            start_date="2025-04-25 10:03:43",
            end_date=t1.strftime("%Y-%m-%d %H:%M:%S"),
            days=392,
            total_consumption=780.0,
            refill_invoice="",
        ))
        # A curated row: same anchor but invoice present — preserved.
        session.add(RefillPeriod(
            start_date="2024-10-10 13:47:57",
            end_date=t1.strftime("%Y-%m-%d %H:%M:%S"),
            days=600,
            total_consumption=500.0,
            refill_invoice="Standard Domestic Oil",
        ))
        await session.commit()

    svc = SettingsService(sf)
    report = await reset_noise_flags(sf, svc, apply=True)

    assert report["periods_deleted"] == 1
    async with sf() as session:
        remaining = (
            await session.execute(select(RefillPeriod))
        ).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].refill_invoice == "Standard Domestic Oil"


@pytest.mark.asyncio
async def test_dry_run_does_not_mutate(sf) -> None:
    t0 = datetime(2026, 5, 24, 12, 0, 0)
    await _seed(sf, [
        _r(t0, air_gap_cm=80.0, litres=520.0),
        _r(t0 + timedelta(minutes=30), air_gap_cm=100.0, litres=329.0, leak="y"),
    ])
    svc = SettingsService(sf)

    report = await reset_noise_flags(sf, svc, apply=False)

    assert report["reset_count"] == 1
    async with sf() as session:
        rows = (await session.execute(select(Reading).order_by(Reading.date))).scalars().all()
    # Dry-run: row still flagged as before.
    assert rows[1].leak_detected == "y"
    assert "noise_suppressed" not in (rows[1].raw_flags or "")
