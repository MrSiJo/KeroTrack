from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import pytest

from kerotrack.analysis.daily_usage import DayUsage, Point, bucket_daily, calibrate


def _series(days, start_l=900.0, hw=0.8, k=0.17, hdd=None, noise=0.0, seed=1):
    rnd = random.Random(seed)
    pts = []
    level = start_l
    d0 = date(2025, 10, 1)
    for i in range(days):
        d = d0 + timedelta(days=i)
        h = hdd(d) if hdd else 0.0
        for hour in (1, 7, 13, 19):
            pts.append(Point(datetime(d.year, d.month, d.day, hour), level + rnd.uniform(-noise, noise)))
        level -= hw + k * h
    return pts


def test_bucket_uses_daily_median_and_drops_big_jumps():
    pts = (
        [Point(datetime(2025, 1, 1, h), 500) for h in (1, 2, 3)]
        + [Point(datetime(2025, 1, 2, h), 498) for h in (1, 2, 3)]
        + [Point(datetime(2025, 1, 3, h), 1100) for h in (1, 2, 3)]  # refill
    )
    days = bucket_daily(pts, max_abs_daily_l=55, exclude_days=set())
    assert days == [DayUsage(date(2025, 1, 2), 2.0)]


def test_bucket_skips_gaps_and_excluded():
    pts = [
        Point(datetime(2025, 1, 1, 1), 500),
        Point(datetime(2025, 1, 3, 1), 490),
        Point(datetime(2025, 1, 4, 1), 489),
    ]
    assert bucket_daily(pts, max_abs_daily_l=55, exclude_days={date(2025, 1, 4)}) == []


def test_calibrate_recovers_known_k_and_hw():
    def hdd(d):
        return 10.0 if d.month in (11, 12, 1, 2) else (3.0 if d.day % 2 else 0.0)

    pts = _series(200, hw=0.8, k=0.17, hdd=hdd, noise=3.0)
    days = bucket_daily(pts, max_abs_daily_l=55, exclude_days=set())
    hdd_map = {du.day: hdd(du.day) for du in days}
    cal = calibrate(days, hdd_map, hw_l_per_day=0.8, slots_per_week=10, fuel_rate_l_per_h=2.33)
    assert cal.k == pytest.approx(0.17, abs=0.02)
    assert cal.free_hw_l == pytest.approx(0.8, abs=0.4)
    assert cal.proposed_burner_minutes == pytest.approx(0.8 * 7 * 60 / (10 * 2.33), rel=0.5)
    assert cal.heating_days >= 30


def test_calibrate_too_few_heating_days_gives_none():
    days = [DayUsage(date(2025, 7, i), 0.8) for i in range(1, 20)]
    cal = calibrate(days, {d.day: 0.0 for d in days}, hw_l_per_day=0.8, slots_per_week=10, fuel_rate_l_per_h=2.33)
    assert cal.k is None and cal.mae_l is None


def test_calibrate_free_fit_on_monthly_aggregates_with_no_zero_hdd_days():
    """HDD is never zero (tank sensor derived), so a daily free fit is
    unidentified; the monthly fit still recovers hw and k."""

    def hdd(d):
        return 10.0 if d.month in (11, 12, 1, 2, 3) else 2.0

    pts = _series(425, hw=0.5, k=0.17, hdd=hdd, noise=3.0)
    days = bucket_daily(pts, max_abs_daily_l=55, exclude_days=set())
    hdd_map = {du.day: hdd(du.day) for du in days}
    cal = calibrate(days, hdd_map, hw_l_per_day=0.5, slots_per_week=10, fuel_rate_l_per_h=2.33)
    assert cal.free_hw_l == pytest.approx(0.5, abs=0.25)
    assert cal.free_k == pytest.approx(0.17, abs=0.03)
    assert cal.proposed_burner_minutes is not None


def test_calibrate_free_fit_needs_three_qualifying_months():
    def hdd(d):
        return 10.0 if d.month == 11 else 2.0

    # 50 days from 2025-10-01: October qualifies (30 days), November (19) does not.
    pts = _series(50, hw=0.5, k=0.17, hdd=hdd)
    days = bucket_daily(pts, max_abs_daily_l=55, exclude_days=set())
    hdd_map = {du.day: hdd(du.day) for du in days}
    cal = calibrate(days, hdd_map, hw_l_per_day=0.5, slots_per_week=10, fuel_rate_l_per_h=2.33)
    assert cal.free_hw_l is None
    assert cal.free_k is None
    assert cal.proposed_burner_minutes is None


def test_calibrate_summer_floor_fallback_when_intercept_not_positive():
    months = [(0.5, 1.0), (1.0, 1.0), (1.5, 1.0), (6.0, 1.5), (12.0, 8.0), (16.0, 13.0)]
    days, hdd_map = [], {}
    for i, (x, y) in enumerate(months):
        year, month = 2025 + (i + 3) // 12, (i + 3) % 12 + 1
        for dd in range(1, 26):
            d = date(year, month, dd)
            days.append(DayUsage(d, y))
            hdd_map[d] = x
    cal = calibrate(days, hdd_map, hw_l_per_day=0.5, slots_per_week=10, fuel_rate_l_per_h=2.33)
    assert cal.free_hw_l is not None and cal.free_hw_l < 0
    assert cal.hw_floor_l == pytest.approx(0.249, abs=0.01)
    assert cal.proposed_burner_minutes == pytest.approx(
        cal.hw_floor_l * 7 * 60 / (10 * 2.33)
    )
