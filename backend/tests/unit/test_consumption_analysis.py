"""Consumption analysis output shape, persistence, and v1 algorithm parity.

Covers the v1 algorithm restoration (backlog A1):
- Hot-water baseline floor on warm/zero-HDD days
- Bounded look-back (30-60 days) when post-refill window is long
- Monthly seasonal heating factor table from real Nest hours data
- estimated_days_remaining cap (700 when the projection never reaches reserve)
- Per-pair refill-aware walker for total_consumption

And the buy planner changes (spec A3, A5, A6): hot water from the boiler
schedule, heating as ``k x today's HDD`` (``heating_estimate_basis="model"``)
and the runway keys taken from the ``normal`` seasonal projection.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.consumption import (
    _seasonal_heating_factor,
    compute,
    run_analysis,
)
from kerotrack.analysis.hot_water import hw_litres_per_day_avg
from kerotrack.projection.service import DEFAULT_K, load_hw, project
from kerotrack.models.hdd import HddDatum
from kerotrack.models.reading import Reading
from kerotrack.models.refill import ActualRefillCost
from kerotrack.publish.mqtt_publisher import MqttPublisher
from kerotrack.pubsub.bus import PubSubBus


pytestmark = pytest.mark.asyncio


REQUIRED_KEYS = {
    "latest_reading_date",
    "latest_analysis_date",
    "latest_reading_refill_detected",
    "latest_reading_leak_detected",
    "days_since_refill",
    "total_consumption_since_refill",
    "avg_daily_consumption_l",
    "estimated_days_remaining",
    "estimated_empty_date",
    "consumption_per_hdd_l",
    "upcoming_month_hdd",
    "estimated_daily_consumption_hdd_l",
    "estimated_daily_hot_water_consumption_l",
    "estimated_daily_heating_consumption_l",
    "seasonal_heating_factor",
    "remaining_days_empty_hdd",
    "remaining_date_empty_hdd",
    "heating_estimate_basis",
}


async def _seed_readings(sf: async_sessionmaker, count: int = 10) -> None:
    async with sf() as session:
        for i in range(count):
            session.add(
                Reading(
                    date=f"2026-04-{15 + i:02d} 12:00:00",
                    id="probe",
                    temperature=12.0 + i * 0.1,
                    litres_remaining=1000.0 - i * 5.0,
                    air_gap_cm=40.0 + i * 0.5,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
        await session.commit()


async def test_compute_returns_full_payload(sf: async_sessionmaker, seeded_settings) -> None:
    await _seed_readings(sf)
    payload = await compute(sf, seeded_settings)
    assert payload is not None
    assert REQUIRED_KEYS.issubset(payload.keys())


async def test_compute_returns_none_with_insufficient_data(
    sf: async_sessionmaker, seeded_settings
) -> None:
    payload = await compute(sf, seeded_settings)
    assert payload is None


async def test_run_analysis_persists_and_publishes(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_readings(sf)

    class Recorder:
        calls = []

        async def publish(self, topic, body, *, qos=0, retain=False):
            type(self).calls.append((topic, body, retain))

    rec = Recorder()
    publisher = MqttPublisher(client=rec)
    bus = PubSubBus()
    sub = bus.subscribe("analysis")

    payload = await run_analysis(
        sf=sf, settings_service=seeded_settings, publisher=publisher, pubsub=bus
    )
    assert payload is not None
    assert Recorder.calls and Recorder.calls[0][0] == "oiltank/analysis"
    channel, body = await sub.get()
    assert channel == "analysis"
    assert body["estimated_days_remaining"] == payload["estimated_days_remaining"]


async def test_anchor_finds_refill_far_outside_recent_window(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """A refill from a year ago must still anchor 'since refill' totals,
    even if there are thousands of newer readings on top."""
    async with sf() as session:
        session.add(
            Reading(
                date="2025-04-26 09:00:00",
                id="probe",
                litres_remaining=1100.0,
                air_gap_cm=20.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        for i in range(300):
            session.add(
                Reading(
                    date=f"2025-{(i % 12) + 1:02d}-{(i % 27) + 1:02d} {(i % 23):02d}:00:00",
                    id="probe",
                    litres_remaining=1100.0 - (i * 1.5),
                    air_gap_cm=20.0 + i * 0.05,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
        session.add(
            Reading(
                date="2026-04-26 09:00:00",
                id="probe",
                litres_remaining=550.0,
                air_gap_cm=77.0,
                refill_detected="n",
                leak_detected="n",
            )
        )
        await session.commit()

    payload = await compute(sf, seeded_settings)
    assert payload is not None
    assert payload["days_since_refill"] is not None
    assert 360 <= payload["days_since_refill"] <= 366
    assert 540.0 <= payload["total_consumption_since_refill"] <= 560.0
    assert payload["avg_daily_consumption_l"] > 1.0


async def test_manual_refill_log_is_authoritative_anchor(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """A real refill that lands inside one reading interval looks exactly
    like a multipath spike, so it gets noise-suppressed and never sets
    refill_detected='y'. The operator's manual log (actual_refill_costs)
    is ground truth: days_since_refill must anchor to the most recent
    manual entry, not the stale sensor-detected marker.

    Mirrors the live data: a genuine 2025-04-25 refill was suppressed, so
    the only 'y' marker left was an older refill — leaving days_since_refill
    ~7 months too high until the manual log is consulted.
    """
    async with sf() as session:
        # Stale sensor-detected refill marker (the only 'y' in readings).
        session.add(
            Reading(
                date="2025-04-26 09:00:00",
                id="probe",
                litres_remaining=1100.0,
                air_gap_cm=20.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        # The real, more-recent refill the sensor saw as a spike and
        # suppressed — no 'y' flag, stamped noise_suppressed.
        session.add(
            Reading(
                date="2026-01-01 10:00:00",
                id="probe",
                litres_remaining=1200.0,
                air_gap_cm=12.0,
                refill_detected="n",
                leak_detected="n",
                raw_flags="128:noise_suppressed",
            )
        )
        # First TRUSTED reading at/after the logged refill date — the
        # consumption baseline (operators log the date at/after delivery).
        session.add(
            Reading(
                date="2026-01-01 12:30:00",
                id="probe",
                litres_remaining=1200.0,
                air_gap_cm=12.0,
                refill_detected="n",
                leak_detected="n",
            )
        )
        # Steady draw down to "today".
        session.add(
            Reading(
                date="2026-04-26 09:00:00",
                id="probe",
                litres_remaining=600.0,
                air_gap_cm=72.0,
                refill_detected="n",
                leak_detected="n",
            )
        )
        # Operator's manual log — authoritative last refill.
        session.add(
            ActualRefillCost(
                refill_date="2026-01-01 12:00:00",
                actual_volume_litres=1000.0,
                invoice_ref="Standard Domestic Oil",
            )
        )
        await session.commit()

    payload = await compute(sf, seeded_settings)
    assert payload is not None
    # ~115 days from 2026-01-01 to 2026-04-26, NOT ~365 from 2025-04-26.
    assert payload["days_since_refill"] is not None
    assert 110 <= payload["days_since_refill"] <= 120
    # Baseline is the post-refill ~1200 L reading, so consumption ~600 L.
    assert 580.0 <= payload["total_consumption_since_refill"] <= 620.0


async def test_anchor_falls_back_to_earliest_when_no_refill(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_readings(sf, count=10)
    payload = await compute(sf, seeded_settings)
    assert payload is not None
    assert payload["days_since_refill"] is None
    assert payload["total_consumption_since_refill"] > 0
    assert payload["avg_daily_consumption_l"] > 0


# --- A1: v1 algorithm parity --------------------------------------------------

async def test_seasonal_heating_factor_uses_real_nest_data() -> None:
    # Per v1 oil_analysis.get_seasonal_heating_factor — Nest hours / max(78).
    # January peak should be 1.0; June/July/August zero; April 21/78 ≈ 0.27.
    assert _seasonal_heating_factor(1) == pytest.approx(1.0)
    assert _seasonal_heating_factor(6) == pytest.approx(0.0)
    assert _seasonal_heating_factor(7) == pytest.approx(0.0)
    assert _seasonal_heating_factor(8) == pytest.approx(0.0)
    # April: 21/78
    assert _seasonal_heating_factor(4) == pytest.approx(21 / 78, abs=0.001)
    # November: 29/78
    assert _seasonal_heating_factor(11) == pytest.approx(29 / 78, abs=0.001)


async def test_hot_water_from_default_schedule_matches_v1_figure(seeded_settings) -> None:
    # Spec A3: the default schedule (10 slots/week x 33 burner minutes at
    # 2.33 L/h) reproduces v1's 1.83 L/day, so upgrading changes nothing
    # until calibrated. Replaces the old HW_* constant formula test.
    schedule, minutes, rate = await load_hw(seeded_settings)
    assert hw_litres_per_day_avg(schedule, minutes, rate) == pytest.approx(1.831, abs=0.01)
    # Doubling the fuel rate doubles the figure.
    assert hw_litres_per_day_avg(schedule, minutes, rate * 2) == pytest.approx(3.661, abs=0.01)


async def test_hot_water_floor_applied_on_zero_hdd_summer_day(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """Summer day with HDD=0 and miniscule oil drop must not deflate
    avg_daily below the HW baseline."""
    async with sf() as session:
        # Refill anchor in mid-July.
        session.add(
            Reading(
                date="2026-07-01 09:00:00",
                id="probe",
                litres_remaining=1000.0,
                air_gap_cm=30.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        # 30 summer days, oil drops 0.3 L/day (well below HW baseline).
        for i in range(1, 31):
            session.add(
                Reading(
                    date=f"2026-07-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1000.0 - i * 0.3,
                    air_gap_cm=30.0 + i * 0.05,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
        # Zero HDD across the window.
        for i in range(31):
            session.add(HddDatum(date=f"2026-07-{i + 1:02d}", hdd=0.0))
        await session.commit()

    payload = await compute(sf, seeded_settings)
    assert payload is not None
    # HW baseline ≈ 1.83 L/day; avg must be ≥ that, not the raw 0.3 L/day.
    assert payload["avg_daily_consumption_l"] >= 1.5
    # No HDD → today_HDD=0 → heating clamped to zero.
    assert payload["estimated_daily_heating_consumption_l"] == pytest.approx(0.0)


async def test_heating_estimate_is_k_times_today_hdd(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """Spec A5: heating = k x today's HDD, not the old blend clamped to
    15 L/day. Seven heating days are too few to fit k, so the default k
    applies: 0.16 x 15 HDD = 2.4 L/day despite the 50 L/day drops."""
    async with sf() as session:
        # Refill, then a sequence with one extreme drop.
        session.add(
            Reading(
                date="2026-01-01 09:00:00",
                id="probe",
                litres_remaining=1000.0,
                air_gap_cm=30.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        # 7 days, very heavy heating — 50 L/day on cold days.
        for i in range(1, 8):
            session.add(
                Reading(
                    date=f"2026-01-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1000.0 - i * 50.0,
                    air_gap_cm=30.0 + i * 1.0,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
            session.add(HddDatum(date=f"2026-01-{i + 1:02d}", hdd=15.0))
        await session.commit()

    payload = await compute(sf, seeded_settings)
    assert payload is not None
    assert payload["heating_estimate_basis"] == "model"
    assert payload["estimated_daily_heating_consumption_l"] == pytest.approx(DEFAULT_K * 15.0)
    assert payload["estimated_daily_consumption_hdd_l"] == pytest.approx(
        payload["estimated_daily_hot_water_consumption_l"] + DEFAULT_K * 15.0, abs=0.02
    )


async def test_estimated_days_remaining_capped_in_summer(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """A projection that never reaches reserve inside its 365 day horizon
    reports the 700 day no-HDD cap and no empty date."""
    async with sf() as session:
        # Mid-summer, tiny consumption, lots of oil.
        session.add(
            Reading(
                date="2026-07-01 09:00:00",
                id="probe",
                litres_remaining=1200.0,
                air_gap_cm=20.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        for i in range(1, 31):
            session.add(
                Reading(
                    date=f"2026-07-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1200.0 - i * 0.1,
                    air_gap_cm=20.0 + i * 0.02,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
            session.add(HddDatum(date=f"2026-07-{i + 1:02d}", hdd=0.0))
        await session.commit()

    payload = await compute(sf, seeded_settings)
    assert payload is not None
    # Without the cap this would be many thousands of days.
    assert payload["estimated_days_remaining"] == pytest.approx(700.0)
    assert payload["estimated_empty_date"] is None
    assert payload["remaining_date_empty_hdd"] is None


async def test_avg_daily_uses_simple_weekly_delta_not_per_pair_sum(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """v1 derives avg_daily_consumption_l from a simple 7-day delta
    (earliest - latest), not from summing per-pair drops across all
    readings. The per-pair walker over-counts every sensor jitter
    (e.g. 200 → 150 → 200 reads as +50 L of bogus consumption), which
    is why a noisy sensor with a real ~5 L/day draw would otherwise
    yield triple-digit averages."""
    async with sf() as session:
        # Refill anchor a year ago.
        session.add(
            Reading(
                date="2025-04-26 09:00:00",
                id="probe",
                litres_remaining=1000.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        # Last 7 days: 200 readings/day (every ~7 min) with realistic
        # ±5 L jitter around a slow 5 L/day downward trend.
        base = 800.0
        seed = 0
        for day in range(7, 0, -1):
            for slot in range(48):
                seed += 1
                jitter = ((seed * 37) % 11 - 5)  # deterministic ±5 L
                date = f"2026-04-{20 + (7 - day):02d} {slot // 2:02d}:{(slot % 2) * 30:02d}:00"
                session.add(
                    Reading(
                        date=date,
                        id="probe",
                        litres_remaining=base + jitter,
                        refill_detected="n",
                        leak_detected="n",
                    )
                )
            base -= 5.0  # real consumption: 5 L/day
        # Final reading "today".
        session.add(
            Reading(
                date="2026-04-27 09:00:00",
                id="probe",
                litres_remaining=base,
                refill_detected="n",
                leak_detected="n",
            )
        )
        await session.commit()

    payload = await compute(sf, seeded_settings)
    assert payload is not None
    # Expect ~5 L/day, not the 100+ L/day a per-pair walker on jittery
    # data would produce.
    assert 1.0 <= payload["avg_daily_consumption_l"] <= 15.0


async def test_per_pair_walker_ignores_refill_spikes(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """A mid-window refill spike must not zero-out total_consumption."""
    async with sf() as session:
        # Initial refill anchor.
        session.add(
            Reading(
                date="2026-02-01 09:00:00",
                id="probe",
                litres_remaining=400.0,
                air_gap_cm=80.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        # Steady consumption for 10 days.
        for i in range(1, 11):
            session.add(
                Reading(
                    date=f"2026-02-{i + 1:02d} 09:00:00",
                    id="probe",
                    litres_remaining=400.0 - i * 5.0,
                    air_gap_cm=80.0 + i * 0.5,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
            session.add(HddDatum(date=f"2026-02-{i + 1:02d}", hdd=12.0))
        # Mid-window REFILL (litres jumps up by 800).
        session.add(
            Reading(
                date="2026-02-12 09:00:00",
                id="probe",
                litres_remaining=1150.0,
                air_gap_cm=10.0,
                refill_detected="y",
                leak_detected="n",
            )
        )
        # More steady consumption after refill.
        for i in range(1, 6):
            session.add(
                Reading(
                    date=f"2026-02-{12 + i:02d} 09:00:00",
                    id="probe",
                    litres_remaining=1150.0 - i * 5.0,
                    air_gap_cm=10.0 + i * 0.5,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
            session.add(HddDatum(date=f"2026-02-{12 + i:02d}", hdd=12.0))
        await session.commit()

    payload = await compute(sf, seeded_settings)
    assert payload is not None
    # Total since latest refill (which is 2026-02-12) should be ~25 L,
    # not the negative jump from the refill.
    assert payload["total_consumption_since_refill"] >= 20.0
    assert payload["total_consumption_since_refill"] <= 30.0
    # avg_daily must be positive and around 5 L/day.
    assert payload["avg_daily_consumption_l"] >= 1.5


# --- Buy planner: model heating and seasonal runway (spec A5, A6) ------------

async def _seed_low_tank(sf: async_sessionmaker, *, today_hdd: float = 0.0) -> datetime:
    """Ten summer days falling 1 L/day to a latest level of 403 L."""
    latest = datetime(2026, 8, 31, 9, 0)
    async with sf() as session:
        for i in range(10):
            when = latest - timedelta(days=9 - i)
            session.add(
                Reading(
                    date=when.strftime("%Y-%m-%d %H:%M:%S"),
                    id="probe",
                    litres_remaining=412.0 - i,
                    refill_detected="n",
                    leak_detected="n",
                )
            )
            hdd = today_hdd if i == 9 else 0.0
            session.add(HddDatum(date=when.strftime("%Y-%m-%d"), hdd=hdd))
        await session.commit()
    return latest


async def test_model_basis_and_zero_heating_on_zero_hdd(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_low_tank(sf)
    payload = await compute(sf, seeded_settings)
    assert payload is not None
    assert payload["heating_estimate_basis"] == "model"
    assert payload["estimated_daily_heating_consumption_l"] == 0
    assert payload["estimated_daily_hot_water_consumption_l"] == pytest.approx(1.83, abs=0.01)


async def test_empty_date_comes_from_seasonal_projection(
    sf: async_sessionmaker, seeded_settings
) -> None:
    """403 L with a 100 L reserve at ~1.83 L/day runs out in ~166 days. The
    old flat rate divided all 403 L by 1.83 (~220 days, to empty not reserve)."""
    latest = await _seed_low_tank(sf)
    payload = await compute(sf, seeded_settings)
    assert payload is not None

    bundle = await project(sf, seeded_settings, now=latest)
    assert bundle is not None
    run_out = bundle.outcomes["normal"].run_out
    assert run_out is not None
    days = (run_out - latest.date()).days
    assert payload["estimated_empty_date"] == f"{run_out.isoformat()} 00:00:00"
    assert payload["remaining_date_empty_hdd"] == payload["estimated_empty_date"]
    assert payload["estimated_days_remaining"] == pytest.approx(days)
    assert payload["remaining_days_empty_hdd"] == pytest.approx(days)
    assert 164 <= days <= 168
    # Not the old latest / 1.83 flat rate.
    old_flat_days = 403.0 / 1.831
    assert abs(payload["estimated_days_remaining"] - old_flat_days) > 30


async def test_heating_uses_projection_k_when_today_is_cold(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_low_tank(sf, today_hdd=10.0)
    payload = await compute(sf, seeded_settings)
    assert payload is not None
    assert payload["heating_estimate_basis"] == "model"
    assert payload["estimated_daily_heating_consumption_l"] == pytest.approx(DEFAULT_K * 10.0)


async def test_projection_failure_falls_back_to_legacy(
    sf: async_sessionmaker, seeded_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kerotrack.analysis.consumption as consumption

    async def boom(*args, **kwargs):
        raise RuntimeError("projection exploded")

    monkeypatch.setattr(consumption, "project", boom)
    latest = await _seed_low_tank(sf)
    payload = await compute(sf, seeded_settings)
    assert payload is not None
    assert payload["heating_estimate_basis"] == "legacy"
    # Legacy flat rate: 403 L / max(weekly avg, 1.83 L/day hot water).
    assert payload["estimated_days_remaining"] == pytest.approx(403.0 / 1.83, abs=1.0)
    expected = latest + timedelta(days=payload["estimated_days_remaining"])
    assert payload["estimated_empty_date"][:10] == expected.strftime("%Y-%m-%d")
