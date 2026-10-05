"""Nest heating hours model (pure, standard library only).

The boiler fires the same way for hot water and heating, and the Nest
decides heating demand, so measured heating hours separate the two far
better than tank temperature degree days. See
``docs/superpowers/specs/2026-10-05-nest-heating-model.md``.

Calibration fits per day means per calendar month, with x the month's
Nest hours divided by its days:

* **Fixed fit** (drives the projection and the analysis): hot water held at
  the schedule figure, exactly like the HDD path, so it is never double
  counted: ``a = sum((y - hw_sched) * x) / sum(x * x)`` over months with
  hours > 0.
* **Free fit** (burner minutes proposal only): ordinary least squares of
  ``y = hw_per_day + a_free * x``.

This is the spec's monthly ``used_month = hw * days + a * nest_hours``
divided through by the month's days. Fitting means instead of totals keeps
months with a few missing usage days unbiased and weights every month
equally. Months whose mean usage is below ``MIN_PLAUSIBLE_L_PER_DAY`` are
sensor blind (impossible while the hot water schedule runs) and are left
out of both fits.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
import math
from datetime import date, timedelta

from kerotrack.analysis.daily_usage import MIN_DAYS_PER_MONTH, DayUsage

MIN_NEST_FIT_MONTHS = 6
MIN_ZERO_HEATING_MONTHS = 2
MIN_NEST_MONTHS_FOR_MODEL = 12
MIN_PLAUSIBLE_L_PER_DAY = 0.25


@dataclass(frozen=True, slots=True)
class NestCalibration:
    a: float | None  # litres per heating hour, hot water fixed at the schedule
    hw_per_day: float | None  # free fit hot water litres per day (the intercept)
    months_used: int  # months with Nest hours, enough usage days, not blind
    zero_months: int  # of those, months with zero heating hours
    mae_l: float | None  # mean abs error of the fixed fit's monthly means, L/day
    a_free: float | None = None  # litres per heating hour from the free fit
    months_excluded: int = 0  # sensor blind months left out


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _days_in(month_key: str) -> int:
    year, month = (int(p) for p in month_key.split("-"))
    return calendar.monthrange(year, month)[1]


def monthly_usage(days: list[DayUsage]) -> dict[str, tuple[float, int]]:
    """``{"YYYY-MM": (mean litres per day, days)}`` for well covered months.

    Months with fewer than ``MIN_DAYS_PER_MONTH`` bucketed days are dropped.
    """
    by_month: dict[str, list[float]] = defaultdict(list)
    for d in days:
        by_month[_month_key(d.day)].append(d.used_l)
    return {
        key: (sum(values) / len(values), len(values))
        for key, values in by_month.items()
        if len(values) >= MIN_DAYS_PER_MONTH
    }


def calibrate_nest(
    month_usage: dict[str, tuple[float, int]],
    nest_hours: dict[str, float],
    *,
    hw_fixed: float,
    min_months: int = MIN_NEST_FIT_MONTHS,
    min_zero_months: int = MIN_ZERO_HEATING_MONTHS,
    min_plausible_l_per_day: float = MIN_PLAUSIBLE_L_PER_DAY,
) -> NestCalibration:
    """Fixed hot water fit of ``a`` plus a free fit for the burner proposal.

    Both need ``min_months`` usable months (in both inputs, not sensor
    blind). The fixed fit also needs some heating hours; the free fit also
    needs ``min_zero_months`` months with zero heating hours (so hot water
    is anchored by data) and some spread in hours. A failed fit gives None.
    """
    rows: list[tuple[float, float]] = []  # (hours per day, litres per day)
    zero = 0
    excluded = 0
    for key, (mean_used, _n) in month_usage.items():
        hours = nest_hours.get(key)
        if hours is None:
            continue
        if mean_used < min_plausible_l_per_day:
            excluded += 1
            continue
        if hours <= 0:
            zero += 1
        rows.append((max(hours, 0.0) / _days_in(key), mean_used))

    n = len(rows)
    if n < min_months:
        return NestCalibration(None, None, n, zero, None, None, excluded)

    a: float | None = None
    mae: float | None = None
    heating = [(x, y) for x, y in rows if x > 0]
    sum_x2 = sum(x * x for x, _ in heating)
    if sum_x2 > 0:
        a = sum((y - hw_fixed) * x for x, y in heating) / sum_x2
        mae = sum(abs(y - (hw_fixed + a * x)) for x, y in rows) / n

    a_free: float | None = None
    hw: float | None = None
    if zero >= min_zero_months:
        mean_x = sum(x for x, _ in rows) / n
        mean_y = sum(y for _, y in rows) / n
        sxx = sum((x - mean_x) ** 2 for x, _ in rows)
        if sxx > 0:
            a_free = sum((x - mean_x) * (y - mean_y) for x, y in rows) / sxx
            hw = mean_y - a_free * mean_x
    return NestCalibration(a, hw, n, zero, mae, a_free, excluded)


def expected_hours_fn(nest_hours: dict[str, float]) -> Callable[[date], float]:
    """Expected heating hours on a day: that calendar month's mean across
    every year with data, divided by the month's days. 0.0 without data."""
    by_month: dict[int, list[float]] = defaultdict(list)
    for key, hours in nest_hours.items():
        by_month[int(key[5:7])].append(max(float(hours), 0.0))
    month_mean = {m: sum(v) / len(v) for m, v in by_month.items() if v}

    def expected(d: date) -> float:
        mean = month_mean.get(d.month)
        if mean is None:
            return 0.0
        return mean / calendar.monthrange(d.year, d.month)[1]

    return expected


def daily_heating_hours(
    start: date, end: date, *, daily: dict[str, float], monthly: dict[str, float]
) -> list[dict[str, object]]:
    """One ``{"date", "hours", "source"}`` per day from ``start`` to ``end``.

    Source order: a daily row (``daily``), else that month's total spread
    evenly over its days (``monthly``), else the calendar month's mean
    across every year (``average``, as the projection uses).
    """
    average = expected_hours_fn(monthly)
    out: list[dict[str, object]] = []
    d = start
    while d <= end:
        key = d.isoformat()
        day_value = daily.get(key)
        month_value = monthly.get(_month_key(d))
        if day_value is not None and math.isfinite(day_value) and day_value >= 0:
            hours, source = float(day_value), "daily"
        elif month_value is not None:
            hours = max(float(month_value), 0.0) / calendar.monthrange(d.year, d.month)[1]
            source = "monthly"
        else:
            hours, source = average(d), "average"
        out.append({"date": key, "hours": round(hours, 3), "source": source})
        d += timedelta(days=1)
    return out


def nest_model_active(nest_hours: dict[str, float], a: float | None) -> bool:
    """The Nest model runs with >= 12 months of data covering all 12
    calendar months, and a positive ``a``.

    Every calendar month must be present because ``expected_hours_fn``
    reads a missing month as zero hours, which would silently drop that
    month's heating from the projection.
    """
    if a is None or a <= 0 or len(nest_hours) < MIN_NEST_MONTHS_FOR_MODEL:
        return False
    calendar_months = {int(key[5:7]) for key in nest_hours}
    return calendar_months == set(range(1, 13))
