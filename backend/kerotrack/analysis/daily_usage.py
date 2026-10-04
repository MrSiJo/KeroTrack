"""Daily usage bucketing and calibration fit (pure, standard library only).

Turns tank readings into litres used per calendar day, then fits litres per
heating degree day (k) and the hot water base against a daily HDD series.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True, slots=True)
class Point:
    when: datetime
    litres: float


@dataclass(frozen=True, slots=True)
class DayUsage:
    day: date
    used_l: float  # may be negative (sensor noise); noise cancels in the fit


@dataclass(frozen=True, slots=True)
class Calibration:
    k: float | None  # L per HDD with hw fixed at the schedule figure
    hw_fixed_l: float
    free_hw_l: float | None  # intercept of the free fit
    free_k: float | None
    proposed_burner_minutes: float | None
    mae_l: float | None  # mean abs error of the fixed-hw model, L/day
    days_used: int
    heating_days: int


def bucket_daily(
    points: list[Point], *, max_abs_daily_l: float, exclude_days: set[date]
) -> list[DayUsage]:
    """Litres used per day from consecutive daily median levels.

    Non consecutive days are skipped (no interpolation). A day is dropped when
    it or the previous day is excluded, or the jump exceeds ``max_abs_daily_l``.
    """
    by_day: dict[date, list[float]] = defaultdict(list)
    for p in points:
        by_day[p.when.date()].append(p.litres)
    level = {d: statistics.median(v) for d, v in by_day.items()}

    out: list[DayUsage] = []
    for d in sorted(level):
        prev = d - timedelta(days=1)
        if prev not in level:
            continue
        if d in exclude_days or prev in exclude_days:
            continue
        used = level[prev] - level[d]
        if abs(used) > max_abs_daily_l:
            continue
        out.append(DayUsage(d, used))
    return out


def calibrate(
    days: list[DayUsage],
    hdd_by_day: dict[date, float],
    *,
    hw_l_per_day: float,
    slots_per_week: float,
    fuel_rate_l_per_h: float,
    min_heating_days: int = 30,
) -> Calibration:
    """Fit k (hw fixed) and a free intercept/slope fit of used = a + b * hdd."""
    pairs = [(d.used_l, hdd_by_day[d.day]) for d in days if d.day in hdd_by_day]
    heating = [(u, h) for u, h in pairs if h > 0]

    k: float | None = None
    mae: float | None = None
    if len(heating) >= min_heating_days:
        sum_h2 = sum(h * h for _, h in heating)
        if sum_h2 > 0:
            k = sum((u - hw_l_per_day) * h for u, h in heating) / sum_h2
            mae = sum(abs(u - (hw_l_per_day + k * h)) for u, h in pairs) / len(pairs)

    free_a: float | None = None
    free_b: float | None = None
    if len({h for _, h in pairs}) >= 2:
        n = len(pairs)
        mean_h = sum(h for _, h in pairs) / n
        mean_u = sum(u for u, _ in pairs) / n
        sxx = sum((h - mean_h) ** 2 for _, h in pairs)
        if sxx > 0:
            free_b = sum((h - mean_h) * (u - mean_u) for u, h in pairs) / sxx
            free_a = mean_u - free_b * mean_h

    minutes: float | None = None
    if free_a is not None and free_a > 0 and slots_per_week > 0 and fuel_rate_l_per_h > 0:
        minutes = free_a * 7 * 60 / (slots_per_week * fuel_rate_l_per_h)

    return Calibration(
        k=k,
        hw_fixed_l=hw_l_per_day,
        free_hw_l=free_a,
        free_k=free_b,
        proposed_burner_minutes=minutes,
        mae_l=mae,
        days_used=len(pairs),
        heating_days=len(heating),
    )
