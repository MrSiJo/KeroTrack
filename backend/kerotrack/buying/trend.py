"""Price trend guide: when might the buy trigger be reached? (pure, stdlib only)

A rough, clearly hedged guide, not a forecast. The trend is measured from
the most recent price peak with a Theil-Sen slope (the median of pairwise
slopes), so one odd day cannot swing it, and it is projected forward in a
straight line to the trigger. It never feeds the buy signal or alerts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from statistics import median

LOOKBACK_DAYS = 60
MIN_DAYS_SINCE_PEAK = 10
MIN_POINTS = 7
# Falling slower than this (pence per litre per day) is treated as flat.
FLAT_PPL_PER_DAY = 0.05
MAX_HORIZON_DAYS = 183

# Statuses
TOO_EARLY = "too_early"
NO_TARGET = "no_target"
AT_TARGET = "at_target"
NOT_FALLING = "not_falling"
FALLING = "falling"
AFTER_ORDER_BY = "after_order_by"
TOO_FAR = "too_far"


@dataclass(frozen=True)
class PriceTrend:
    status: str
    peak_date: str | None = None
    peak_ppl: float | None = None
    current_ppl: float | None = None
    ppl_per_week: float | None = None
    projected_date: str | None = None
    target_ppl: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _theil_sen(points: list[tuple[int, float]]) -> tuple[float, float]:
    slopes = [
        (y2 - y1) / (x2 - x1)
        for i, (x1, y1) in enumerate(points)
        for x2, y2 in points[i + 1 :]
        if x2 != x1
    ]
    slope = median(slopes)
    intercept = median(y - slope * x for x, y in points)
    return slope, intercept


def price_trend(
    daily: list[tuple[date, float]],
    *,
    today: date,
    target_ppl: float | None,
    order_by: date | None,
) -> PriceTrend:
    """Project the recent trend in `daily` (real pence per litre) to `target_ppl`.

    `daily` holds one price per day, VAT and fees included (the trigger's
    basis); only the last ``LOOKBACK_DAYS`` are used.
    """
    since = today - timedelta(days=LOOKBACK_DAYS)
    series = sorted((d, p) for d, p in daily if since <= d <= today and p > 0)
    if not series:
        return PriceTrend(TOO_EARLY)
    latest_ppl = series[-1][1]
    if not target_ppl or target_ppl <= 0:
        return PriceTrend(NO_TARGET, current_ppl=round(latest_ppl, 2))
    if latest_ppl <= target_ppl:
        return PriceTrend(AT_TARGET, current_ppl=round(latest_ppl, 2), target_ppl=target_ppl)

    peak_ppl = max(p for _, p in series)
    peak_date = max(d for d, p in series if p == peak_ppl)
    after = [((d - today).days, p) for d, p in series if d >= peak_date]
    if (today - peak_date).days < MIN_DAYS_SINCE_PEAK or len(after) < MIN_POINTS:
        return PriceTrend(
            TOO_EARLY,
            peak_date=peak_date.isoformat(),
            peak_ppl=round(peak_ppl, 2),
            current_ppl=round(latest_ppl, 2),
            target_ppl=target_ppl,
        )

    slope, fitted_today = _theil_sen(after)
    base = dict(
        peak_date=peak_date.isoformat(),
        peak_ppl=round(peak_ppl, 2),
        current_ppl=round(fitted_today, 2),
        ppl_per_week=round(slope * 7, 2),
        target_ppl=target_ppl,
    )
    if slope > -FLAT_PPL_PER_DAY:
        return PriceTrend(NOT_FALLING, **base)

    days = max(1, round((fitted_today - target_ppl) / -slope))
    projected = today + timedelta(days=days)
    if days > MAX_HORIZON_DAYS:
        return PriceTrend(TOO_FAR, **base)
    status = AFTER_ORDER_BY if order_by is not None and projected > order_by else FALLING
    return PriceTrend(status, projected_date=projected.isoformat(), **base)
