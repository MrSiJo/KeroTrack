"""Pure recalc unit tests — math + output contract."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from kerotrack.ingest.recalc import (
    PreviousReading,
    RecalcContext,
    calculate_bars,
    calculate_compensated_volume,
    calculate_hdd,
    calculate_seasonal_efficiency,
    decode_status,
    detect_leak,
    detect_refill,
    process,
)


def test_decode_status_known_codes() -> None:
    assert "Initial sync" in decode_status(192)
    assert "Post-sync" in decode_status(128)
    assert "Transitional" in decode_status(144)
    assert "Normal" in decode_status(152)


def test_decode_status_unknown_codes() -> None:
    assert decode_status(255).startswith("Unknown status")
    assert decode_status(None).startswith("Unknown status")
    assert decode_status("garbage").startswith("Unknown status")


def test_process_logs_non_normal_status(caplog) -> None:
    fixture = dict(FIXTURES["canonical"])
    fixture["status"] = 192  # Initial sync
    ctx = _ctx()
    with caplog.at_level("INFO", logger="kerotrack.ingest.recalc"):
        process(fixture, ctx)
    assert any("Initial sync" in record.message for record in caplog.records)


def test_process_silent_on_normal_status(caplog) -> None:
    fixture = dict(FIXTURES["canonical"])
    fixture["status"] = 152  # Normal
    ctx = _ctx()
    with caplog.at_level("INFO", logger="kerotrack.ingest.recalc"):
        process(fixture, ctx)
    assert not any(
        "Sensor status" in record.message for record in caplog.records
    )


FIXTURES = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "watchman_sonic_payloads.json").read_text()
)


def _ctx(**overrides) -> RecalcContext:
    base = dict(
        tank_capacity_l=1225.0,
        tank_height_cm=137.0,
        reference_temperature=15.0,
        thermal_expansion_coefficient=0.0008,
        hdd_base_temperature=15.5,
        refill_threshold_l=100.0,
        leak_threshold_l=100.0,
        leak_rate_per_day_l=10.0,
        max_daily_consumption_warm_l=30.0,
        max_daily_consumption_cold_l=55.0,
        warm_temperature_threshold_c=16.0,
        sanity_safety_multiplier=2.0,
        current_ppl=78.5,
    )
    base.update(overrides)
    return RecalcContext(**base)


def test_hdd_zero_when_warmer_than_base() -> None:
    assert calculate_hdd(20.0, 15.5) == 0.0


def test_hdd_positive_when_colder() -> None:
    assert calculate_hdd(5.5, 15.5) == 10.0


def test_seasonal_efficiency_seasons() -> None:
    assert calculate_seasonal_efficiency(1) == 0.95  # winter
    assert calculate_seasonal_efficiency(4) == 0.97  # spring
    assert calculate_seasonal_efficiency(7) == 0.99  # summer


def test_compensated_volume_at_full() -> None:
    v = calculate_compensated_volume(
        air_gap_cm=0.0,
        temperature=15.0,
        height_cm=137.0,
        capacity_l=1225.0,
        reference_temperature=15.0,
        thermal_expansion_coefficient=0.0008,
    )
    assert v == 1225.0


def test_compensated_volume_at_empty() -> None:
    v = calculate_compensated_volume(
        air_gap_cm=137.0,
        temperature=15.0,
        height_cm=137.0,
        capacity_l=1225.0,
        reference_temperature=15.0,
        thermal_expansion_coefficient=0.0008,
    )
    assert v == 0.0


def test_compensated_volume_temperature_compensation() -> None:
    v_cold = calculate_compensated_volume(
        air_gap_cm=68.5,
        temperature=5.0,
        height_cm=137.0,
        capacity_l=1225.0,
        reference_temperature=15.0,
        thermal_expansion_coefficient=0.0008,
    )
    v_hot = calculate_compensated_volume(
        air_gap_cm=68.5,
        temperature=25.0,
        height_cm=137.0,
        capacity_l=1225.0,
        reference_temperature=15.0,
        thermal_expansion_coefficient=0.0008,
    )
    # Compensation: cold raw volume corrected upwards; hot corrected downwards.
    assert v_cold > 612.5
    assert v_hot < 612.5


@pytest.mark.parametrize(
    "pct,expected",
    [
        (0, 1),
        (10, 1),
        (15, 1),
        (16, 2),
        (50, 5),
        (95, 9),
        (100, 10),
    ],
)
def test_calculate_bars(pct: float, expected: int) -> None:
    assert calculate_bars(pct) == expected


def test_detect_refill_no_history() -> None:
    assert detect_refill(900.0, None, 30.0, None, threshold_l=100.0) == "n"


def test_detect_refill_threshold_met() -> None:
    # Volume increased by 200 L AND air gap dropped by 25 cm.
    assert detect_refill(900.0, 700.0, 30.0, 55.0, threshold_l=100.0) == "y"


def test_detect_refill_threshold_not_met() -> None:
    assert detect_refill(750.0, 700.0, 50.0, 55.0, threshold_l=100.0) == "n"


def test_detect_leak_no_history() -> None:
    assert (
        detect_leak(800.0, None, datetime(2026, 4, 25), None,
                   threshold_l=100.0, leak_rate_per_day_l=10.0)
        == "n"
    )


def test_detect_leak_within_window_above_threshold() -> None:
    a = datetime(2026, 4, 25, 10, 0, 0)
    b = a + timedelta(hours=12)
    # Lost 200 L in 12 h, way over the expected 5 L from leak_rate.
    assert detect_leak(
        700.0, 900.0, b, a, threshold_l=100.0, leak_rate_per_day_l=10.0
    ) == "y"


def test_detect_leak_below_threshold() -> None:
    a = datetime(2026, 4, 25, 10, 0, 0)
    b = a + timedelta(hours=6)
    assert detect_leak(
        890.0, 900.0, b, a, threshold_l=100.0, leak_rate_per_day_l=10.0
    ) == "n"


def test_detect_leak_outside_window() -> None:
    a = datetime(2026, 4, 20)
    b = datetime(2026, 4, 25)
    assert detect_leak(
        700.0, 900.0, b, a, threshold_l=100.0, leak_rate_per_day_l=10.0
    ) == "n"


def test_process_output_matches_v1_schema() -> None:
    result = process(FIXTURES["canonical"], _ctx())
    expected_keys = {
        "date",
        "id",
        "temperature",
        "litres_remaining",
        "litres_used_since_last",
        "percentage_remaining",
        "oil_depth_cm",
        "air_gap_cm",
        "current_ppl",
        "cost_used",
        "cost_to_fill",
        "heating_degree_days",
        "seasonal_efficiency",
        "refill_detected",
        "leak_detected",
        "raw_flags",
        "litres_to_order",
        "bars_remaining",
    }
    assert set(result.keys()) == expected_keys


def test_cost_to_fill_is_string() -> None:
    """Spec §3.1 — KeroDisplay parses cost_to_fill via atof. Must remain a string."""
    result = process(FIXTURES["canonical"], _ctx(current_ppl=78.5))
    assert isinstance(result["cost_to_fill"], str)
    assert isinstance(result["cost_used"], str)


def test_cost_to_fill_zero_when_no_price() -> None:
    result = process(FIXTURES["canonical"], _ctx(current_ppl=None))
    assert result["cost_to_fill"] == "0.00"
    assert result["cost_used"] == "0.00"


def test_refill_detection_after_dip_and_top_up() -> None:
    prev = PreviousReading(
        date=datetime(2026, 4, 30, 12, 0, 0),
        litres_remaining=200.0,
        air_gap_cm=110.0,
    )
    result = process(FIXTURES["post_refill"], _ctx(), previous=prev)
    assert result["refill_detected"] == "y"


def test_first_reading_has_zero_used() -> None:
    result = process(FIXTURES["canonical"], _ctx(), previous=None)
    assert result["litres_used_since_last"] == 0.0


# --------------------------------------------------------------------
# Sanity-bound: suppress refill/leak flags on physically-impossible
# deltas (Watchman Sonic multipath misreads in warm weather).
# --------------------------------------------------------------------


def _payload(*, when: datetime, depth_cm: float, temp_c: float, status: int = 144) -> dict:
    """Build a Watchman Sonic-shaped RTL_433 payload for a given time/depth/temp."""
    return {
        "time": when.strftime("%Y-%m-%d %H:%M:%S"),
        "id": "12345",
        "model": "Oil-SonicSmart",
        "depth_cm": depth_cm,
        "temperature_C": temp_c,
        "status": status,
    }


def _prev_at(when: datetime, *, air_gap_cm: float, litres_remaining: float) -> PreviousReading:
    return PreviousReading(
        date=when,
        litres_remaining=litres_remaining,
        air_gap_cm=air_gap_cm,
    )


def test_sanity_bound_suppresses_false_leak_on_30min_spike() -> None:
    # The exact pattern from May 22-28 2026: prev reading at 80 cm ~520L,
    # next reading 30 min later at 100 cm ~329L (178 L "loss"). Warm.
    prev_dt = datetime(2026, 5, 24, 12, 9, 38)
    curr_dt = prev_dt + timedelta(minutes=30)
    payload = _payload(when=curr_dt, depth_cm=100.0, temp_c=23.0)
    prev = _prev_at(prev_dt, air_gap_cm=80.0, litres_remaining=520.0)

    result = process(payload, _ctx(), previous=prev)

    assert result["leak_detected"] == "n"
    assert result["refill_detected"] == "n"


def test_sanity_bound_suppresses_false_refill_on_30min_dip() -> None:
    # Opposite half of the oscillation: prev at 100 cm ~329L, next at 80 cm ~520L.
    prev_dt = datetime(2026, 5, 24, 12, 39, 38)
    curr_dt = prev_dt + timedelta(minutes=30)
    payload = _payload(when=curr_dt, depth_cm=80.0, temp_c=23.0)
    prev = _prev_at(prev_dt, air_gap_cm=100.0, litres_remaining=329.0)

    result = process(payload, _ctx(), previous=prev)

    assert result["refill_detected"] == "n"
    assert result["leak_detected"] == "n"


def test_sanity_bound_marks_noise_in_raw_flags() -> None:
    prev_dt = datetime(2026, 5, 24, 12, 9, 38)
    curr_dt = prev_dt + timedelta(minutes=30)
    payload = _payload(when=curr_dt, depth_cm=100.0, temp_c=23.0, status=144)
    prev = _prev_at(prev_dt, air_gap_cm=80.0, litres_remaining=520.0)

    result = process(payload, _ctx(), previous=prev)

    # Original status byte preserved, sentinel appended so UI can flag the row.
    assert "noise_suppressed" in str(result["raw_flags"])
    assert "144" in str(result["raw_flags"])


def test_sanity_bound_keeps_raw_depth_and_litres_honest() -> None:
    # Even when we suppress the flags, the persisted depth/air_gap/litres
    # must reflect what the sensor actually reported — we don't want to lose
    # signal that there's noise upstream.
    prev_dt = datetime(2026, 5, 24, 12, 9, 38)
    curr_dt = prev_dt + timedelta(minutes=30)
    payload = _payload(when=curr_dt, depth_cm=100.0, temp_c=23.0)
    prev = _prev_at(prev_dt, air_gap_cm=80.0, litres_remaining=520.0)

    result = process(payload, _ctx(), previous=prev)

    assert result["air_gap_cm"] == 100.0
    assert result["oil_depth_cm"] == 37.0  # 137 - 100
    assert result["litres_remaining"] < 400.0  # ~329, sensor-reported


def test_sanity_bound_applies_when_trusted_is_old_but_sensor_in_cadence() -> None:
    """After several chain-noise rows, the most recent TRUSTED reading
    can be hours old even though the sensor has been broadcasting
    normally every 30 min. The sanity bound must still apply — the
    max-gap watchdog is for genuine outages, not chains of suppressed
    readings.
    """
    trusted_dt = datetime(2026, 5, 28, 16, 10, 0)
    most_recent_dt = datetime(2026, 5, 28, 19, 10, 0)
    curr_dt = datetime(2026, 5, 28, 19, 40, 0)
    payload = _payload(when=curr_dt, depth_cm=94.0, temp_c=20.0)
    prev = PreviousReading(
        date=trusted_dt,
        litres_remaining=520.0,
        air_gap_cm=80.0,
        most_recent_date=most_recent_dt,
    )

    result = process(payload, _ctx(), previous=prev)

    assert result["leak_detected"] == "n"
    assert "noise_suppressed" in str(result["raw_flags"] or "")


def test_sanity_bound_catches_60min_plus_jitter() -> None:
    # Real-world cadence: sensor broadcasts every ~30 min, occasionally
    # missing one. The gap-to-previous then lands at ~3601 s (60 min +
    # broadcast-time jitter). Those must still be caught — they were in
    # the May 2026 multipath fingerprint.
    prev_dt = datetime(2026, 5, 24, 11, 9, 38)
    curr_dt = prev_dt + timedelta(seconds=3602)  # 60 min 2 s
    payload = _payload(when=curr_dt, depth_cm=100.0, temp_c=23.0)
    prev = _prev_at(prev_dt, air_gap_cm=80.0, litres_remaining=520.0)

    result = process(payload, _ctx(), previous=prev)

    assert result["leak_detected"] == "n"
    assert "noise_suppressed" in str(result["raw_flags"] or "")


def test_sanity_bound_skipped_when_interval_exceeds_max_gap() -> None:
    # First reading after a multi-hour gap — sensor offline, settings page open
    # during a refill, whatever. We have no idea what happened, so a 800 L
    # rise across a 21 h gap is a real refill, not a spike to suppress.
    prev_dt = datetime(2026, 4, 30, 12, 0, 0)
    curr_dt = prev_dt + timedelta(hours=21)
    payload = _payload(when=curr_dt, depth_cm=20.0, temp_c=14.0)
    prev = _prev_at(prev_dt, air_gap_cm=110.0, litres_remaining=200.0)

    result = process(payload, _ctx(), previous=prev)

    assert result["refill_detected"] == "y"
    assert "noise_suppressed" not in str(result["raw_flags"] or "")


def test_sanity_bound_suppresses_drop_beyond_max_gap() -> None:
    # The May 29 2026 phantom leak: the sensor missed two broadcasts
    # overnight, so the gap to the previous trusted reading was ~1.5 h —
    # past SANITY_BOUND_MAX_GAP_HOURS (1.25 h). The old symmetric gate
    # disarmed the bound entirely, letting an 80 → 93 cm multipath jump
    # (~116 L "loss" in 90 min) fire as a leak. A *drop* can never beat
    # the consumption budget at any gap length — you cannot burn 116 L of
    # kerosene in 90 min — so leak suppression must stay armed regardless
    # of gap. (Refills, which CAN be large and fast, keep the time gate —
    # see test_sanity_bound_skipped_when_interval_exceeds_max_gap.)
    prev_dt = datetime(2026, 5, 29, 7, 40, 16)
    curr_dt = datetime(2026, 5, 29, 9, 10, 15)  # +1 h 30 min
    payload = _payload(when=curr_dt, depth_cm=93.0, temp_c=14.0)
    prev = _prev_at(prev_dt, air_gap_cm=80.0, litres_remaining=510.5)

    result = process(payload, _ctx(), previous=prev)

    assert result["leak_detected"] == "n"
    assert "noise_suppressed" in str(result["raw_flags"] or "")


def test_sanity_bound_allows_modest_consumption_within_budget() -> None:
    # Tight ×2 budget: cold 30 min budget ≈ 2.3 L. A 0.1 cm air-gap rise
    # (~0.9 L drop) is well within that — must not trip the sanity sentinel.
    prev_dt = datetime(2026, 1, 15, 8, 0, 0)
    curr_dt = prev_dt + timedelta(minutes=30)
    payload = _payload(when=curr_dt, depth_cm=80.1, temp_c=5.0)
    prev = _prev_at(prev_dt, air_gap_cm=80.0, litres_remaining=520.0)

    result = process(payload, _ctx(), previous=prev)

    assert "noise_suppressed" not in str(result["raw_flags"] or "")
    assert result["leak_detected"] == "n"
    assert result["refill_detected"] == "n"


def test_sanity_bound_allows_single_cm_consumption_tick() -> None:
    # The sensor reports air gap as an integer cm. A real consumption
    # "tick" therefore shows up as a 1 cm jump (~9 L on this tank). That
    # must clear the bound — otherwise winter consumption gets eaten by
    # noise suppression.
    prev_dt = datetime(2026, 1, 15, 8, 0, 0)
    curr_dt = prev_dt + timedelta(minutes=30)
    payload = _payload(when=curr_dt, depth_cm=81.0, temp_c=5.0)
    prev = _prev_at(prev_dt, air_gap_cm=80.0, litres_remaining=520.0)

    result = process(payload, _ctx(), previous=prev)

    assert "noise_suppressed" not in str(result["raw_flags"] or "")
