from datetime import date, timedelta

import pytest

from kerotrack.projection.runway import (
    RunwayInputs,
    climatology,
    order_by_date,
    parse_multipliers,
    simulate,
    weekly_points,
)

FLAT_HW = {i: 1.0 for i in range(7)}


def test_flat_summer_still_draws_hot_water_daily():
    r = simulate(RunwayInputs(date(2026, 6, 1), 400.0, 0.17, FLAT_HW, lambda d: 0.0, {}, 100.0, 365))
    assert r.series[1][1] == pytest.approx(399.0)
    assert r.run_out == date(2026, 6, 1) + timedelta(days=300)


def test_heating_and_multiplier_only_touch_heating_term():
    base = simulate(RunwayInputs(date(2026, 11, 1), 1000.0, 0.2, FLAT_HW, lambda d: 10.0, {}, 0.0, 10))
    mild = simulate(RunwayInputs(date(2026, 11, 1), 1000.0, 0.2, FLAT_HW, lambda d: 10.0, {11: 0.5}, 0.0, 10))
    assert 1000.0 - base.series[1][1] == pytest.approx(3.0)
    assert 1000.0 - mild.series[1][1] == pytest.approx(2.0)


def test_already_below_reserve_runs_out_today():
    r = simulate(RunwayInputs(date(2026, 1, 1), 90.0, 0.1, FLAT_HW, lambda d: 0, {}, 100.0, 30))
    assert r.run_out == date(2026, 1, 1)


def test_climatology_same_window_multi_year_else_month_mean():
    data = {date(2024, 1, 10): 10.0, date(2025, 1, 12): 14.0, date(2025, 3, 1): 4.0}
    f = climatology(data)
    assert f(date(2027, 1, 11)) == pytest.approx(12.0)
    assert f(date(2027, 3, 20)) == pytest.approx(4.0)  # one year only -> month mean
    assert f(date(2027, 7, 1)) == 0.0


def test_order_by_adds_winter_extra_only_in_dec_to_feb():
    assert order_by_date(date(2027, 2, 28), lead_days=14, winter_extra_days=7) == date(2027, 2, 7)
    assert order_by_date(date(2027, 6, 30), lead_days=14, winter_extra_days=7) == date(2027, 6, 16)
    assert order_by_date(None, lead_days=14, winter_extra_days=7) is None


def test_parse_multipliers_and_weekly_points():
    assert parse_multipliers({"11": 0.8, "x": 2, "13": 1}) == {11: 0.8}
    s = [(date(2026, 1, 1) + timedelta(days=i), 100.0 - i) for i in range(10)]
    assert weekly_points(s) == [["2026-01-01", 100.0], ["2026-01-08", 93.0], ["2026-01-10", 91.0]]


def test_climatology_wraps_year_end_and_handles_leap_day():
    data = {date(2024, 12, 30): 8.0, date(2025, 1, 2): 12.0, date(2024, 2, 29): 5.0, date(2025, 2, 27): 7.0}
    f = climatology(data)
    assert f(date(2027, 1, 1)) == pytest.approx(10.0)  # wraps Dec 30 and Jan 2
    assert f(date(2028, 2, 29)) == pytest.approx(6.0)  # leap target maps to Feb 28


def test_simulate_365_days_with_climatology_is_fast():
    import time

    data = {date(y, 1, 1) + timedelta(days=i): 5.0 for y in (2023, 2024, 2025) for i in range(365)}
    f = climatology(data)
    t = time.perf_counter()
    simulate(RunwayInputs(date(2026, 10, 4), 900.0, 0.2, FLAT_HW, f, {}, 100.0, 365))
    assert time.perf_counter() - t < 0.5


def test_heating_litres_function_replaces_k_times_hdd():
    # Nest model: heating litres per day come from a * expected_hours(d);
    # k and expected_hdd are ignored, the multiplier still applies.
    inp = RunwayInputs(
        date(2026, 11, 1), 1000.0, 99.0, FLAT_HW, lambda d: 50.0, {11: 0.5}, 0.0, 10,
        heating_l=lambda d: 4.0,
    )
    r = simulate(inp)
    assert 1000.0 - r.series[1][1] == pytest.approx(1.0 + 4.0 * 0.5)
