"""Seasonal runway simulation (pure, no I/O).

Projects the oil level day by day as hot water plus ``k`` times the expected
degree days (scaled by a per month scenario multiplier), to find the run out
date and the order by date.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

_YEAR_LEN = 365  # non leap reference year; Feb 29 is folded onto Feb 28
_REF_YEAR = 2001
_WINTER_MONTHS = frozenset({12, 1, 2})


@dataclass(frozen=True, slots=True)
class RunwayInputs:
    start_day: date
    start_litres: float
    k: float
    hw_by_weekday: dict[int, float]  # litres per weekday index 0..6
    expected_hdd: Callable[[date], float]
    multipliers: dict[int, float]  # month -> heating multiplier; missing = 1.0
    reserve_l: float
    horizon_days: int = 365


@dataclass(frozen=True, slots=True)
class RunwayResult:
    series: list[tuple[date, float]]  # daily, start_day first
    run_out: date | None


def parse_multipliers(raw: dict) -> dict[int, float]:
    """Turn ``{"11": 0.8}`` into ``{11: 0.8}``, ignoring bad keys or values."""
    out: dict[int, float] = {}
    for key, value in (raw or {}).items():
        try:
            month = int(key)
            mult = float(value)
        except (TypeError, ValueError):
            continue
        if 1 <= month <= 12:
            out[month] = mult
    return out


def _slot(d: date) -> int:
    """Day of year index 0..364 in a non leap year (Feb 29 maps to Feb 28)."""
    month, day = d.month, d.day
    if month == 2 and day == 29:
        day = 28
    return date(_REF_YEAR, month, day).timetuple().tm_yday - 1


def climatology(
    hdd_by_day: dict[date, float], *, window_days: int = 7, min_years: int = 2
) -> Callable[[date], float]:
    """Expected degree days for a date from history.

    Mean over entries within +/- ``window_days`` of the same day of year (any
    year) when at least ``min_years`` distinct years contribute, else the mean
    of the same calendar month, else 0.0. Lookup tables are precomputed.
    """
    slot_sum = [0.0] * _YEAR_LEN
    slot_n = [0] * _YEAR_LEN
    slot_years: list[set[int]] = [set() for _ in range(_YEAR_LEN)]
    month_sum = [0.0] * 13
    month_n = [0] * 13
    for d, v in hdd_by_day.items():
        s = _slot(d)
        slot_sum[s] += v
        slot_n[s] += 1
        slot_years[s].add(d.year)
        month_sum[d.month] += v
        month_n[d.month] += 1

    window_mean: list[float | None] = []
    for s in range(_YEAR_LEN):
        total = 0.0
        n = 0
        years: set[int] = set()
        for off in range(-window_days, window_days + 1):
            idx = (s + off) % _YEAR_LEN
            total += slot_sum[idx]
            n += slot_n[idx]
            years |= slot_years[idx]
        window_mean.append(total / n if n and len(years) >= min_years else None)

    month_mean = [month_sum[m] / month_n[m] if month_n[m] else 0.0 for m in range(13)]

    def expected(d: date) -> float:
        w = window_mean[_slot(d)]
        return w if w is not None else month_mean[d.month]

    return expected


def simulate(inp: RunwayInputs) -> RunwayResult:
    """Project litres daily over the horizon and find the first run out date."""
    litres = inp.start_litres
    series: list[tuple[date, float]] = [(inp.start_day, litres)]
    run_out: date | None = inp.start_day if litres <= inp.reserve_l else None
    prev = inp.start_day
    for i in range(1, inp.horizon_days + 1):
        d = inp.start_day + timedelta(days=i)
        draw = inp.hw_by_weekday.get(prev.weekday(), 0.0) + (
            inp.k * inp.expected_hdd(prev) * inp.multipliers.get(prev.month, 1.0)
        )
        litres -= max(draw, 0.0)
        series.append((d, litres))
        if run_out is None and litres <= inp.reserve_l:
            run_out = d
        prev = d
    return RunwayResult(series=series, run_out=run_out)


def order_by_date(run_out: date | None, *, lead_days: int, winter_extra_days: int) -> date | None:
    """Latest sensible order date: run out minus lead time, plus winter slack."""
    if run_out is None:
        return None
    cand = run_out - timedelta(days=lead_days)
    span = (run_out - cand).days
    if any((cand + timedelta(days=n)).month in _WINTER_MONTHS for n in range(span + 1)):
        cand -= timedelta(days=winter_extra_days)
    return cand


def weekly_points(series: list[tuple[date, float]]) -> list[list]:
    """``[[iso, litres_1dp], ...]`` for every 7th day plus the last point."""
    if not series:
        return []
    picked = series[::7]
    if picked[-1][0] != series[-1][0]:
        picked.append(series[-1])
    return [[d.isoformat(), round(v, 1)] for d, v in picked]
