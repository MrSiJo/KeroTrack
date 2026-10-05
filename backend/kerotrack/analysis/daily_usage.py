"""Daily usage bucketing and calibration fit (pure, standard library only).

Turns tank readings into litres used per calendar day, then fits litres per
heating degree day (k) and the hot water base against a daily HDD series.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

MIN_DAYS_PER_MONTH = 20
MIN_MONTHS_FOR_FREE_FIT = 3


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
    hw_floor_l: float | None = None  # summer floor hot water, used when the free intercept is <= 0
    # Nest heating hours model (analysis.nest_model). heating_model is "nest"
    # when the projection uses it, else "hdd". l_per_heating_hour is the
    # fixed hot water fit (what the projection uses); hw_per_day_nest and
    # l_per_heating_hour_free are the free fit, used only for the burner
    # minutes proposal (under "nest" proposed_burner_minutes comes from
    # hw_per_day_nest). All are reported whenever the fit succeeded.
    heating_model: str = "hdd"
    l_per_heating_hour: float | None = None
    nest_months_used: int = 0
    hw_per_day_nest: float | None = None
    l_per_heating_hour_free: float | None = None
    nest_months_excluded: int = 0


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
    """Fit k (hw fixed, daily) and a free fit of used = a + b * hdd (monthly)."""
    pairs = [(d.used_l, hdd_by_day[d.day]) for d in days if d.day in hdd_by_day]
    heating = [(u, h) for u, h in pairs if h > 0]

    k: float | None = None
    mae: float | None = None
    if len(heating) >= min_heating_days:
        sum_h2 = sum(h * h for _, h in heating)
        if sum_h2 > 0:
            k = sum((u - hw_l_per_day) * h for u, h in heating) / sum_h2
            mae = sum(abs(u - (hw_l_per_day + k * h)) for u, h in pairs) / len(pairs)

    # The free fit runs on calendar month aggregates: tank derived HDD is
    # almost never zero, so a daily intercept is unidentified.
    free_a: float | None = None
    free_b: float | None = None
    hw_floor: float | None = None
    by_month: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    for d in days:
        if d.day in hdd_by_day:
            by_month[(d.day.year, d.day.month)].append((d.used_l, hdd_by_day[d.day]))
    months = [
        (
            sum(h for _, h in rows) / len(rows),
            sum(u for u, _ in rows) / len(rows),
        )
        for rows in by_month.values()
        if len(rows) >= MIN_DAYS_PER_MONTH
    ]
    if len(months) >= MIN_MONTHS_FOR_FREE_FIT and len({x for x, _ in months}) >= 2:
        n = len(months)
        mean_x = sum(x for x, _ in months) / n
        mean_y = sum(y for _, y in months) / n
        sxx = sum((x - mean_x) ** 2 for x, _ in months)
        if sxx > 0:
            free_b = sum((x - mean_x) * (y - mean_y) for x, y in months) / sxx
            free_a = mean_y - free_b * mean_x
            if free_a <= 0:
                # Tank temperature HDD separates hot water from heating
                # poorly: fall back to the 3 lowest HDD months.
                low = sorted(months)[:MIN_MONTHS_FOR_FREE_FIT]
                floor = sum(y - free_b * x for x, y in low) / len(low)
                hw_floor = max(floor, 0.0)

    minutes: float | None = None
    hw_for_minutes = hw_floor if hw_floor is not None else free_a
    if hw_for_minutes is not None and hw_for_minutes > 0 and slots_per_week > 0 and fuel_rate_l_per_h > 0:
        minutes = hw_for_minutes * 7 * 60 / (slots_per_week * fuel_rate_l_per_h)

    return Calibration(
        k=k,
        hw_fixed_l=hw_l_per_day,
        free_hw_l=free_a,
        free_k=free_b,
        proposed_burner_minutes=minutes,
        mae_l=mae,
        days_used=len(pairs),
        heating_days=len(heating),
        hw_floor_l=hw_floor,
    )
