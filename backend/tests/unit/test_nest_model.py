"""Nest heating hours model: monthly aggregation, calibration, expected hours.

All figures are synthetic.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import pytest

from kerotrack.analysis.daily_usage import DayUsage
from kerotrack.analysis.nest_model import (
    MIN_NEST_MONTHS_FOR_MODEL,
    MIN_PLAUSIBLE_L_PER_DAY,
    calibrate_nest,
    expected_hours_fn,
    monthly_usage,
    nest_model_active,
)

HW = 0.9
A = 0.7
# Synthetic monthly heating hours by calendar month (zero in summer).
HOURS = {1: 70.0, 2: 50.0, 3: 40.0, 4: 20.0, 5: 4.0, 6: 0.0, 7: 0.0, 8: 0.0,
         9: 0.0, 10: 6.0, 11: 30.0, 12: 45.0}


def _days_for(year: int, month: int, *, hours: float, n_days: int | None = None) -> list[DayUsage]:
    dim = calendar.monthrange(year, month)[1]
    per_day = HW + A * hours / dim
    n = dim if n_days is None else n_days
    return [DayUsage(date(year, month, 1) + timedelta(days=i), per_day) for i in range(n)]


def test_monthly_usage_keeps_months_with_enough_days() -> None:
    days = _days_for(2025, 1, hours=70.0) + _days_for(2025, 2, hours=50.0, n_days=10)
    out = monthly_usage(days)
    assert set(out) == {"2025-01"}
    mean, n = out["2025-01"]
    assert n == 31
    assert mean == pytest.approx(HW + A * 70.0 / 31)


def test_calibrate_nest_recovers_hw_and_a() -> None:
    days: list[DayUsage] = []
    nest: dict[str, float] = {}
    for m in range(1, 13):
        days += _days_for(2025, m, hours=HOURS[m])
        nest[f"2025-{m:02d}"] = HOURS[m]
    cal = calibrate_nest(monthly_usage(days), nest, hw_fixed=HW)
    assert cal.a == pytest.approx(A, abs=1e-6)
    assert cal.a_free == pytest.approx(A, abs=1e-6)
    assert cal.hw_per_day == pytest.approx(HW, abs=1e-6)
    assert cal.months_used == 12
    assert cal.months_excluded == 0
    assert cal.zero_months == 4
    assert cal.mae_l == pytest.approx(0.0, abs=1e-6)


def test_calibrate_nest_needs_six_months() -> None:
    days: list[DayUsage] = []
    nest: dict[str, float] = {}
    for m in (6, 7, 8, 11, 12):
        days += _days_for(2025, m, hours=HOURS[m])
        nest[f"2025-{m:02d}"] = HOURS[m]
    cal = calibrate_nest(monthly_usage(days), nest, hw_fixed=HW)
    assert cal.a is None
    assert cal.a_free is None
    assert cal.hw_per_day is None
    assert cal.months_used == 5


def test_calibrate_nest_needs_two_zero_months() -> None:
    days: list[DayUsage] = []
    nest: dict[str, float] = {}
    for m in (1, 2, 3, 4, 5, 6, 10, 11):
        days += _days_for(2025, m, hours=HOURS[m])
        nest[f"2025-{m:02d}"] = HOURS[m]
    cal = calibrate_nest(monthly_usage(days), nest, hw_fixed=HW)
    # The free fit needs two zero months to anchor hot water; the fixed fit
    # does not (hot water comes from the schedule).
    assert cal.a_free is None
    assert cal.hw_per_day is None
    assert cal.a == pytest.approx(A, abs=1e-6)
    assert cal.zero_months == 1


def test_calibrate_nest_ignores_months_without_nest_hours() -> None:
    days: list[DayUsage] = []
    nest: dict[str, float] = {}
    for m in range(1, 13):
        days += _days_for(2025, m, hours=HOURS[m])
        if m != 1:
            nest[f"2025-{m:02d}"] = HOURS[m]
    cal = calibrate_nest(monthly_usage(days), nest, hw_fixed=HW)
    assert cal.months_used == 11
    assert cal.a == pytest.approx(A, abs=1e-6)


def test_expected_hours_is_calendar_month_mean_per_day() -> None:
    fn = expected_hours_fn({"2024-01": 62.0, "2025-01": 93.0, "2025-07": 0.0})
    assert fn(date(2026, 1, 15)) == pytest.approx((62.0 + 93.0) / 2 / 31)
    assert fn(date(2026, 7, 1)) == 0.0
    assert fn(date(2026, 3, 1)) == 0.0  # no data for March


def test_nest_model_active_rules() -> None:
    twelve = {f"2025-{m:02d}": HOURS[m] for m in range(1, 13)}
    assert MIN_NEST_MONTHS_FOR_MODEL == 12
    assert nest_model_active(twelve, 0.7) is True
    assert nest_model_active(twelve, None) is False
    assert nest_model_active(twelve, -0.1) is False
    eleven = dict(list(twelve.items())[:11])
    assert nest_model_active(eleven, 0.7) is False
    # Twelve or more rows are not enough when a calendar month is missing:
    # expected hours would read 0 for it and silently drop that month's heating.
    no_january = {f"{y}-{m:02d}": HOURS[m] for y in (2024, 2025) for m in range(2, 13)}
    assert len(no_january) == 22
    assert nest_model_active(no_january, 0.7) is False


def test_fixed_fit_holds_hot_water_at_the_schedule_value() -> None:
    # Data generated with hw 0.9; the schedule says 1.4. The fixed fit keeps
    # hot water at 1.4 and only fits a, so it does not double count hot
    # water; the free fit still recovers the true intercept.
    days: list[DayUsage] = []
    nest: dict[str, float] = {}
    for m in range(1, 13):
        days += _days_for(2025, m, hours=HOURS[m])
        nest[f"2025-{m:02d}"] = HOURS[m]
    usage = monthly_usage(days)
    cal = calibrate_nest(usage, nest, hw_fixed=1.4)
    rows = [(HOURS[m] / calendar.monthrange(2025, m)[1], usage[f"2025-{m:02d}"][0])
            for m in range(1, 13) if HOURS[m] > 0]
    want = sum((y - 1.4) * x for x, y in rows) / sum(x * x for x, _ in rows)
    assert cal.a == pytest.approx(want)
    assert cal.a < A
    assert cal.a_free == pytest.approx(A, abs=1e-6)
    assert cal.hw_per_day == pytest.approx(HW, abs=1e-6)


def test_sensor_blind_months_are_excluded_from_both_fits() -> None:
    assert MIN_PLAUSIBLE_L_PER_DAY == 0.25
    days: list[DayUsage] = []
    nest: dict[str, float] = {}
    for m in range(1, 13):
        days += _days_for(2025, m, hours=HOURS[m])
        nest[f"2025-{m:02d}"] = HOURS[m]
    # Two blind summer months a year later: the sensor reads almost nothing.
    for m, per_day in ((7, 0.09), (8, -0.5)):
        dim = calendar.monthrange(2026, m)[1]
        days += [DayUsage(date(2026, m, 1) + timedelta(days=i), per_day) for i in range(dim)]
        nest[f"2026-{m:02d}"] = 0.0
    cal = calibrate_nest(monthly_usage(days), nest, hw_fixed=HW)
    assert cal.months_excluded == 2
    assert cal.months_used == 12
    assert cal.a == pytest.approx(A, abs=1e-6)
    assert cal.a_free == pytest.approx(A, abs=1e-6)
    assert cal.hw_per_day == pytest.approx(HW, abs=1e-6)
