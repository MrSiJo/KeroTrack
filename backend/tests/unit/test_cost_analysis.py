"""Cost analysis: golden-path output, period generation, HDD metrics, weighted averages.

Covers backlog items A2 (refill_periods writer), A3 (per-period reading-based
cost + actual-cost preference), A4 (HDD cost metrics + measured efficiency),
A5 (leap-year days_in_month + weighted historical averages).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.cost import (
    _days_in_month_for,
    _detect_periods,
    _weighted_avg,
    compute,
    run_cost_analysis,
)
from kerotrack.models.hdd import HddDatum
from kerotrack.models.reading import Reading
from kerotrack.models.refill import ActualRefillCost
from kerotrack.models.refill_period import RefillPeriod
from kerotrack.publish.mqtt_publisher import MqttPublisher
from kerotrack.pubsub.bus import PubSubBus


pytestmark = pytest.mark.asyncio


REQUIRED_KEYS = {
    "analysis_date",
    "latest_period_start",
    "latest_period_end",
    "latest_period_days",
    "latest_refill_amount",
    "latest_refill_cost",
    "latest_refill_ppl",
    "latest_total_consumption",
    "latest_total_cost",
    "latest_daily_cost",
    "latest_weekly_cost",
    "latest_monthly_cost",
    "days_since_refill",
    "avg_period_cost",
    "avg_period_consumption",
    "avg_daily_cost",
    "avg_weekly_cost",
    "avg_monthly_cost",
    "avg_annual_cost",
    "avg_cost_per_hdd",
    "avg_consumption_per_hdd",
    "avg_cost_per_kwh",
    "avg_daily_energy_kwh",
    "avg_cost_per_heat_unit",
    "total_refill_periods",
    "percentage_with_actual_data",
    "energy_efficiency",
    "analysis_data",
}


async def _seed_periods(sf: async_sessionmaker) -> None:
    async with sf() as session:
        for i in range(3):
            session.add(
                RefillPeriod(
                    start_date=f"2025-{i + 1:02d}-01 00:00:00",
                    end_date=f"2025-{i + 2:02d}-01 00:00:00",
                    days=30,
                    total_consumption=300.0 - i * 10,
                    total_cost=200.0 + i * 5,
                    daily_cost=6.5 + i * 0.1,
                    weekly_cost=45.5,
                    monthly_cost=200.0,
                    refill_amount_liters=400.0,
                    refill_ppl=80.0,
                    refill_cost=320.0,
                )
            )
        await session.commit()


async def test_cost_compute_returns_full_payload(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_periods(sf)
    payload = await compute(sf, seeded_settings)
    assert payload is not None
    assert REQUIRED_KEYS.issubset(payload.keys())


async def test_cost_compute_returns_none_without_periods(
    sf: async_sessionmaker, seeded_settings
) -> None:
    assert await compute(sf, seeded_settings) is None


async def test_run_cost_analysis_publishes_to_correct_topic(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_periods(sf)

    class Recorder:
        calls = []

        async def publish(self, topic, body, *, qos=0, retain=False):
            type(self).calls.append((topic, body, retain))

    rec = Recorder()
    publisher = MqttPublisher(client=rec)
    payload = await run_cost_analysis(
        sf=sf, settings_service=seeded_settings, publisher=publisher
    )
    assert payload is not None
    assert Recorder.calls[0][0] == "oiltank/cost_analysis"


# --- A5: leap-year + weighted averages ---------------------------------------

async def test_days_in_month_leap_year_aware() -> None:
    # Leap year 2024 → 366/12 = 30.5
    assert _days_in_month_for(2024) == pytest.approx(366 / 12, abs=0.001)
    # Common year 2025 → 365/12 ≈ 30.417
    assert _days_in_month_for(2025) == pytest.approx(365 / 12, abs=0.001)


async def test_weighted_avg_weights_by_days() -> None:
    # Period 1: cost 100 over 10 days; Period 2: cost 200 over 30 days.
    # Time-weighted average daily cost should weigh the 30-day period more.
    pairs = [(100.0 / 10, 10), (200.0 / 30, 30)]
    avg = _weighted_avg(pairs)
    expected = (100.0 + 200.0) / 40
    assert avg == pytest.approx(expected, abs=0.01)


async def test_weighted_avg_handles_empty_and_zero_weights() -> None:
    assert _weighted_avg([]) == 0.0
    assert _weighted_avg([(5.0, 0), (10.0, 0)]) == 0.0


# --- A2/A3: _detect_periods writes refill_periods from sensor data ----------

async def test_detect_periods_writes_rows_from_sensor_refills(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """Two sensor-detected refills → one period row (between them)."""
    async with sf() as session:
        # Refill #1 — tank topped up to 1100 L on 2025-10-01.
        session.add(
            Reading(
                date="2025-10-01 09:00:00",
                id="probe",
                litres_remaining=1100.0,
                current_ppl=70.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        # Steady consumption for 30 days at varying ppl.
        for i in range(1, 31):
            session.add(
                Reading(
                    date=f"2025-10-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1100.0 - i * 10.0,
                    current_ppl=70.0 + i * 0.5,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
        # Refill #2 on 2025-11-01 — back up to 1200 L.
        session.add(
            Reading(
                date="2025-11-01 09:00:00",
                id="probe",
                litres_remaining=1200.0,
                current_ppl=85.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        await session.commit()

    written = await _detect_periods(sf, seeded_settings)
    assert written == 1
    async with sf() as session:
        from sqlalchemy import select

        rows = (await session.execute(select(RefillPeriod))).scalars().all()
    assert len(rows) == 1
    p = rows[0]
    assert p.start_date == "2025-10-01 09:00:00"
    assert p.end_date == "2025-11-01 09:00:00"
    # Reading-based consumption ≈ 300 L (1100 − 800 just before refill #2).
    assert p.total_consumption is not None
    assert 250.0 <= p.total_consumption <= 320.0
    # Days = 31.
    assert p.days == 31
    # Cost > 0, weighted by per-pair PPL.
    assert (p.total_cost or 0) > 0
    # used_actual_cost = 0 (no actual_refill_costs row).
    assert p.used_actual_cost == 0


async def test_detect_periods_idempotent(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """Running _detect_periods twice produces the same row count."""
    async with sf() as session:
        session.add(
            Reading(
                date="2025-10-01 09:00:00",
                id="probe",
                litres_remaining=1100.0,
                current_ppl=70.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        for i in range(1, 31):
            session.add(
                Reading(
                    date=f"2025-10-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1100.0 - i * 10.0,
                    current_ppl=70.0,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
        session.add(
            Reading(
                date="2025-11-01 09:00:00",
                id="probe",
                litres_remaining=1200.0,
                current_ppl=85.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        await session.commit()

    first = await _detect_periods(sf, seeded_settings)
    second = await _detect_periods(sf, seeded_settings)
    assert first == 1
    assert second in (0, 1)  # upsert may re-touch the row, but no duplicates.

    async with sf() as session:
        from sqlalchemy import select

        rows = (await session.execute(select(RefillPeriod))).scalars().all()
    assert len(rows) == 1


async def test_detect_periods_prefers_actual_refill_costs(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """If an actual_refill_costs row matches a refill date (within 24h),
    its invoiced amounts override sensor-derived figures."""
    async with sf() as session:
        session.add(
            Reading(
                date="2025-10-01 09:00:00",
                id="probe",
                litres_remaining=1100.0,
                current_ppl=70.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        for i in range(1, 31):
            session.add(
                Reading(
                    date=f"2025-10-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1100.0 - i * 10.0,
                    current_ppl=70.0,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
        session.add(
            Reading(
                date="2025-11-01 09:00:00",
                id="probe",
                litres_remaining=1200.0,
                current_ppl=85.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        # Actual invoice for the 2025-11-01 refill.
        session.add(
            ActualRefillCost(
                refill_date="2025-11-01 10:30:00",  # within 24h
                actual_volume_litres=420.0,
                actual_ppl=82.5,
                total_cost=346.50,
                invoice_ref="INV-001",
            )
        )
        await session.commit()

    await _detect_periods(sf, seeded_settings)
    async with sf() as session:
        from sqlalchemy import select

        row = (await session.execute(select(RefillPeriod))).scalar_one()
    assert row.used_actual_cost == 1
    assert row.refill_amount_liters == pytest.approx(420.0)
    assert row.refill_ppl == pytest.approx(82.5)
    assert row.refill_cost == pytest.approx(346.50)
    assert row.refill_invoice == "INV-001"


# --- A4: HDD cost metrics + measured efficiency -------------------------------

async def test_detect_periods_populates_hdd_metrics(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """When HDD data exists for the period, total_hdd / cost_per_hdd /
    consumption_per_hdd land on the row."""
    async with sf() as session:
        session.add(
            Reading(
                date="2025-10-01 09:00:00",
                id="probe",
                litres_remaining=1100.0,
                current_ppl=70.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        for i in range(1, 31):
            session.add(
                Reading(
                    date=f"2025-10-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1100.0 - i * 10.0,
                    current_ppl=70.0,
                    seasonal_efficiency=92.0,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
            session.add(HddDatum(date=f"2025-10-{i + 1:02d}", hdd=12.0))
        session.add(
            Reading(
                date="2025-11-01 09:00:00",
                id="probe",
                litres_remaining=1200.0,
                current_ppl=85.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        await session.commit()

    await _detect_periods(sf, seeded_settings)
    async with sf() as session:
        from sqlalchemy import select

        row = (await session.execute(select(RefillPeriod))).scalar_one()
    assert row.total_hdd is not None
    assert row.total_hdd > 300  # 30 × 12 = 360
    assert (row.cost_per_hdd or 0) > 0
    assert (row.consumption_per_hdd or 0) > 0


async def test_compute_uses_measured_efficiency_when_available(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """energy_efficiency in the payload comes from readings.seasonal_efficiency
    when present, not the boiler nameplate."""
    async with sf() as session:
        session.add(
            Reading(
                date="2025-10-01 09:00:00",
                id="probe",
                litres_remaining=1100.0,
                current_ppl=70.0,
                seasonal_efficiency=88.0,  # measured 88%
                refill_detected="y",
                leak_detected="n",
            )
        )
        for i in range(1, 31):
            session.add(
                Reading(
                    date=f"2025-10-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1100.0 - i * 10.0,
                    current_ppl=70.0,
                    seasonal_efficiency=88.0,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
        session.add(
            Reading(
                date="2025-11-01 09:00:00",
                id="probe",
                litres_remaining=1200.0,
                current_ppl=85.0,
                seasonal_efficiency=88.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        await session.commit()

    await _detect_periods(sf, seeded_settings)
    payload = await compute(sf, seeded_settings)
    assert payload is not None
    # Should be ~0.88 (measured), not 0.99 (configured boiler.efficiency_pct/100).
    assert 0.85 <= payload["energy_efficiency"] <= 0.91


async def test_run_cost_analysis_writes_periods_via_detect(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """run_cost_analysis must call _detect_periods before compute, so a
    fresh DB with refill markers but no period rows still gets analysed."""
    async with sf() as session:
        session.add(
            Reading(
                date="2025-10-01 09:00:00",
                id="probe",
                litres_remaining=1100.0,
                current_ppl=70.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        for i in range(1, 31):
            session.add(
                Reading(
                    date=f"2025-10-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1100.0 - i * 10.0,
                    current_ppl=70.0,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
        session.add(
            Reading(
                date="2025-11-01 09:00:00",
                id="probe",
                litres_remaining=1200.0,
                current_ppl=85.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        await session.commit()

    class Recorder:
        calls = []

        async def publish(self, topic, body, *, qos=0, retain=False):
            type(self).calls.append((topic, body, retain))

    rec = Recorder()
    publisher = MqttPublisher(client=rec)
    payload = await run_cost_analysis(
        sf=sf, settings_service=seeded_settings, publisher=publisher
    )
    assert payload is not None
    assert payload["total_refill_periods"] >= 1


async def test_persist_upserts_on_same_day(sf: async_sessionmaker) -> None:
    """Two runs on the same day update one row instead of appending
    near-duplicates keyed on second-resolution timestamps (KERO-L5)."""
    from sqlalchemy import select

    from kerotrack.analysis.cost import _persist
    from kerotrack.models.cost_analysis import CostAnalysis

    await _persist(
        sf, {"analysis_date": "2026-07-08 07:00:00", "latest_total_cost": 10.0}
    )
    await _persist(
        sf, {"analysis_date": "2026-07-08 09:30:00", "latest_total_cost": 12.5}
    )
    await _persist(
        sf, {"analysis_date": "2026-07-09 07:00:00", "latest_total_cost": 13.0}
    )

    async with sf() as session:
        rows = (
            (await session.execute(select(CostAnalysis))).scalars().all()
        )
    by_date = {r.analysis_date: r.latest_total_cost for r in rows}
    assert by_date == {
        "2026-07-08 09:30:00": 12.5,
        "2026-07-09 07:00:00": 13.0,
    }
