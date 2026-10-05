"""Price trend guide (pure): projection from the recent peak to the trigger."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from kerotrack.buying.trend import (
    AFTER_ORDER_BY,
    AT_TARGET,
    FALLING,
    NO_TARGET,
    NOT_FALLING,
    TOO_EARLY,
    TOO_FAR,
    price_trend,
)

TODAY = date(2026, 10, 5)


def series(values: list[float]) -> list[tuple[date, float]]:
    """One value per day, the last one today."""
    start = TODAY - timedelta(days=len(values) - 1)
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def falling(days: int, start: float, per_day: float) -> list[float]:
    return [start - per_day * i for i in range(days)]


def test_falling_projects_the_date_the_target_is_reached() -> None:
    # Peak 120p, falling 0.25p/day for 20 days to 115.25p; 95p is 81 days out.
    t = price_trend(series(falling(20, 120.0, 0.25)), today=TODAY, target_ppl=95.0,
                    order_by=date(2027, 1, 22))
    assert t.status == FALLING
    assert t.ppl_per_week == pytest.approx(-1.75)
    assert t.peak_date == (TODAY - timedelta(days=19)).isoformat()
    assert t.projected_date == (TODAY + timedelta(days=81)).isoformat()


def test_trend_is_measured_from_the_most_recent_peak() -> None:
    # A rise to the peak, then a fall: the rise must not cancel the fall.
    values = [100 + i for i in range(15)] + falling(20, 114.0, 0.2)
    t = price_trend(series(values), today=TODAY, target_ppl=95.0, order_by=None)
    assert t.status == FALLING and t.peak_ppl == 114.0
    assert t.ppl_per_week == pytest.approx(-1.4)


def test_one_odd_day_does_not_swing_the_slope() -> None:
    values = falling(20, 120.0, 0.25)
    values[12] = 100.0  # a glitch
    t = price_trend(series(values), today=TODAY, target_ppl=95.0, order_by=None)
    assert t.ppl_per_week == pytest.approx(-1.75)


def test_projection_after_order_by() -> None:
    t = price_trend(series(falling(20, 120.0, 0.25)), today=TODAY, target_ppl=95.0,
                    order_by=date(2026, 11, 30))
    assert t.status == AFTER_ORDER_BY and t.projected_date is not None


def test_too_far_beyond_six_months() -> None:
    t = price_trend(series(falling(20, 120.0, 0.06)), today=TODAY, target_ppl=95.0,
                    order_by=None)
    assert t.status == TOO_FAR and t.projected_date is None


def test_flat_or_rising_is_not_falling() -> None:
    flat = price_trend(series([110.0] * 15 + [111.0] + [110.0] * 12), today=TODAY,
                       target_ppl=95.0, order_by=None)
    assert flat.status == NOT_FALLING
    # A rise to today's peak: the peak is today, too early to measure a fall.
    rising = price_trend(series([100 + i for i in range(20)]), today=TODAY,
                         target_ppl=95.0, order_by=None)
    assert rising.status == TOO_EARLY


def test_too_early_after_a_recent_peak() -> None:
    values = [100.0] * 20 + [120.0] + falling(5, 119.0, 0.5)
    t = price_trend(series(values), today=TODAY, target_ppl=95.0, order_by=None)
    assert t.status == TOO_EARLY and t.peak_ppl == 120.0


def test_at_or_below_target_and_no_target() -> None:
    assert price_trend(series(falling(20, 100.0, 0.5)), today=TODAY, target_ppl=95.0,
                       order_by=None).status == AT_TARGET
    assert price_trend(series(falling(20, 120.0, 0.25)), today=TODAY, target_ppl=0.0,
                       order_by=None).status == NO_TARGET
    assert price_trend([], today=TODAY, target_ppl=95.0, order_by=None).status == TOO_EARLY


def test_only_the_last_60_days_count() -> None:
    old_peak = [(TODAY - timedelta(days=200), 150.0)]
    t = price_trend(old_peak + series(falling(20, 120.0, 0.25)), today=TODAY,
                    target_ppl=95.0, order_by=None)
    assert t.peak_ppl == 120.0
