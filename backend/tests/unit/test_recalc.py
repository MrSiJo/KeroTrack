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
    detect_leak,
    detect_refill,
    process,
)


FIXTURES = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "watchman_sonic_payloads.json").read_text()
)


def _ctx(**overrides) -> RecalcContext:
    base = dict(
        tank_capacity_l=1225.0,
        tank_length_cm=178.5,
        tank_width_cm=75.0,
        tank_height_cm=137.0,
        thermal_coefficient=0.0007,
        reference_temperature=15.0,
        thermal_expansion_coefficient=0.0008,
        hdd_base_temperature=15.5,
        refill_threshold_l=100.0,
        leak_threshold_l=100.0,
        leak_rate_per_day_l=10.0,
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
