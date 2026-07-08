"""Consumption analysis port (was `oil_analysis.py`).

Reads from `readings`, computes the analysis payload (every key per spec
§3.2 and the HA contract §3.2 extension), persists to `analysis_results`,
and publishes the full payload to `oiltank/analysis`.

This is the v1 algorithm restored (backlog A1):

1. Hot-water baseline derived from boiler.fuel_rate_l_per_h × 10 scheduled
   sessions/week × 0.5h ÷ 7 × 1.1 buffer; used as a floor on per-day
   consumption when HDD=0 so summer days don't deflate the average.
2. Bounded look-back window: ``min(60, max(30, days_since_refill))`` so a
   long post-refill window doesn't get poisoned by stale summer averages.
3. Per-pair refill-aware walker for `total_consumption` (rejects negative
   spikes greater than `detection.refill_threshold_l`).
4. Heating estimate blends 7-day vs long-window components (0.65/0.35),
   scales by `today_HDD/avg_7d_HDD` clamped 0.6-1.6, then clamps the
   result to [MIN_HEATING_L, MAX_HEATING_L].
5. Monthly seasonal heating factor from real Nest hours data
   (78,43,43,21,3,0,0,0,0,5,29,37) — April resolves to ~0.27 instead of
   the bucketed 0.7 the first port used.
6. ``estimated_days_remaining`` capped at 400 (HDD>0) or 700 (HDD=0) so
   summer scenarios don't produce multi-thousand-day projections.

Output shape is unchanged — every key in spec §3.2 still present, same
types, same rounding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.hdd_rollup import aggregate_daily_hdd
from kerotrack.clock import local_now, local_now_str, parse_local
from kerotrack.models.analysis_result import AnalysisResult
from kerotrack.models.hdd import HddDatum
from kerotrack.models.reading import Reading, trusted_readings_clause
from kerotrack.models.refill import ActualRefillCost
from kerotrack.publish.mqtt_publisher import MqttPublisher
from kerotrack.pubsub.bus import PubSubBus
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)


MIN_CONSUMPTION_L_PER_DAY = 0.01
MIN_HEATING_L = 0.5
MAX_HEATING_L = 15.0
HDD_SCALE_MIN = 0.6
HDD_SCALE_MAX = 1.6
HEATING_BLEND_RECENT = 0.65
HEATING_BLEND_LONG = 0.35
LOOKBACK_MIN_DAYS = 30
LOOKBACK_MAX_DAYS = 60
DAYS_REMAINING_CAP_HDD = 400.0
DAYS_REMAINING_CAP_NO_HDD = 700.0
HW_BUFFER_FACTOR = 1.1
HW_SESSIONS_PER_WEEK = 10  # 1/day × 4 weekdays + 2/day × 3 weekend days
HW_SESSION_HOURS = 0.5


# Real Nest heating-hours data (v1's get_seasonal_heating_factor).
_HEATING_HOURS_BY_MONTH: dict[int, int] = {
    1: 78,
    2: 43,
    3: 43,
    4: 21,
    5: 3,
    6: 0,
    7: 0,
    8: 0,
    9: 0,
    10: 5,
    11: 29,
    12: 37,
}
_HEATING_MAX = max(_HEATING_HOURS_BY_MONTH.values())


@dataclass(frozen=True, slots=True)
class _Snapshot:
    capacity_l: float
    base_temperature: float
    ema_alpha: float
    kwh_per_liter: float
    co2_per_liter: float
    fuel_rate_l_per_h: float
    refill_threshold_l: float


async def _snapshot(svc: SettingsService) -> _Snapshot:
    return _Snapshot(
        capacity_l=float(await svc.get("tank.capacity_l")),
        base_temperature=float(await svc.get("analysis.hdd_base_temperature")),
        ema_alpha=float(await svc.get("analysis.ema_alpha")),
        kwh_per_liter=float(await svc.get("analysis.kwh_per_liter")),
        co2_per_liter=float(await svc.get("analysis.co2_per_liter")),
        fuel_rate_l_per_h=float(await svc.get("boiler.fuel_rate_l_per_h")),
        refill_threshold_l=float(await svc.get("detection.refill_threshold_l")),
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _seasonal_heating_factor(month: int) -> float:
    """Proportion of peak heating usage for a given month, from real Nest data."""
    if _HEATING_MAX <= 0:
        return 0.0
    return _HEATING_HOURS_BY_MONTH.get(month, 0) / _HEATING_MAX


def _hot_water_baseline_l_per_day(fuel_rate_l_per_h: float) -> float:
    """Estimate scheduled-HW daily consumption with v1's buffer."""
    base = (HW_SESSIONS_PER_WEEK * HW_SESSION_HOURS * fuel_rate_l_per_h) / 7.0
    return base * HW_BUFFER_FACTOR


async def _latest_reading(sf: async_sessionmaker) -> Reading | None:
    """Most recent TRUSTED reading — skips noise_suppressed rows so
    `total_consumption_since_refill` and the windowed deltas don't
    anchor to a sensor multipath spike."""
    async with sf() as session:
        return (
            await session.execute(
                select(Reading)
                .where(trusted_readings_clause())
                .order_by(desc(Reading.date))
                .limit(1)
            )
        ).scalar_one_or_none()


async def _earliest_reading(sf: async_sessionmaker) -> Reading | None:
    async with sf() as session:
        return (
            await session.execute(
                select(Reading).order_by(asc(Reading.date)).limit(1)
            )
        ).scalar_one_or_none()


async def _latest_refill_anchor(sf: async_sessionmaker) -> Reading | None:
    """Most recent sensor-detected refill marker — the fallback anchor.

    Excludes ``noise_suppressed`` rows so a phantom refill spike can't
    masquerade as the last refill and reset the counter to ~0.
    """
    async with sf() as session:
        return (
            await session.execute(
                select(Reading)
                .where(
                    Reading.refill_detected == "y",
                    trusted_readings_clause(),
                )
                .order_by(desc(Reading.date))
                .limit(1)
            )
        ).scalar_one_or_none()


async def _latest_manual_refill_date(sf: async_sessionmaker) -> str | None:
    """Most recent operator-entered refill date — the authoritative record.

    A genuine refill that lands inside a single reading interval (179 →
    1110 L in 30 min, seen 2025-04-25) is indistinguishable from a Watchman
    Sonic multipath spike by magnitude alone, so the sanity bound suppresses
    it and it never sets ``refill_detected='y'``. The manual ``actual_refill_costs``
    log is therefore the only reliable source for "last refill" — readings
    alone leave ``days_since_refill`` months stale.
    """
    async with sf() as session:
        return (
            await session.execute(
                select(ActualRefillCost.refill_date)
                .order_by(desc(ActualRefillCost.refill_date))
                .limit(1)
            )
        ).scalar_one_or_none()


async def _first_trusted_reading_on_or_after(
    sf: async_sessionmaker, date_str: str
) -> Reading | None:
    """First non-noise reading at or after ``date_str`` — the post-refill
    tank level used as the consumption baseline."""
    async with sf() as session:
        return (
            await session.execute(
                select(Reading)
                .where(
                    Reading.date >= date_str,
                    trusted_readings_clause(),
                )
                .order_by(asc(Reading.date))
                .limit(1)
            )
        ).scalar_one_or_none()


async def _readings_in_window(
    sf: async_sessionmaker, start_dt: datetime, end_dt: datetime
) -> list[Reading]:
    """Window readings for delta walkers.

    Excludes rows tagged ``noise_suppressed`` in ``raw_flags`` — those
    carry the sensor's bad litres/air_gap, so feeding them into the
    consumption/cost per-pair walkers would over-count usage on every
    noise→good transition. Rows with NULL raw_flags (pre-feature data)
    are kept.
    """
    start = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    async with sf() as session:
        return (
            (
                await session.execute(
                    select(Reading)
                    .where(
                        Reading.date >= start,
                        Reading.date <= end,
                        trusted_readings_clause(),
                    )
                    .order_by(asc(Reading.date))
                )
            )
            .scalars()
            .all()
        )


async def _hdd_in_window(
    sf: async_sessionmaker, start_dt: datetime, end_dt: datetime
) -> dict[str, float]:
    """Return `{YYYY-MM-DD: hdd}` for every row in the window."""
    start = start_dt.strftime("%Y-%m-%d")
    end = end_dt.strftime("%Y-%m-%d")
    async with sf() as session:
        rows = (
            (
                await session.execute(
                    select(HddDatum)
                    .where(HddDatum.date >= start, HddDatum.date <= end)
                    .order_by(asc(HddDatum.date))
                )
            )
            .scalars()
            .all()
        )
    return {r.date: float(r.hdd or 0) for r in rows}


def _per_pair_total_consumption(
    readings: list[Reading], refill_threshold_l: float
) -> float:
    """v1's calculate_total_consumption — ignore refills (large positive
    jumps) and any pair where litres_remaining went up."""
    total = 0.0
    for prev, curr in zip(readings, readings[1:]):
        used = float(prev.litres_remaining or 0) - float(curr.litres_remaining or 0)
        if used < -refill_threshold_l:
            continue
        if used > 0:
            total += used
    return total


def _usage_stats(
    readings: list[Reading],
    hdd_data: dict[str, float],
    daily_hw_l: float,
    refill_threshold_l: float,
) -> dict[str, float]:
    """v1's compute_usage_stats — splits HW-only days from heating days,
    floors HW-only days to the HW baseline."""
    total_days = 0.0
    adjusted_total = 0.0
    heating_total = 0.0
    heat_day_count = 0.0

    for prev, curr in zip(readings, readings[1:]):
        used = float(prev.litres_remaining or 0) - float(curr.litres_remaining or 0)
        if used < -refill_threshold_l:
            continue
        if used <= 0:
            continue
        prev_dt = parse_local(prev.date)
        curr_dt = parse_local(curr.date)
        if prev_dt is None or curr_dt is None:
            continue
        days_delta = (curr_dt - prev_dt).total_seconds() / 86400
        if days_delta <= 0:
            continue
        per_day = used / days_delta
        curr_day = curr_dt.strftime("%Y-%m-%d")
        curr_hdd = hdd_data.get(curr_day, 0.0)

        if curr_hdd == 0:
            per_day = max(per_day, daily_hw_l)
        else:
            heat_day_count += days_delta

        adjusted_total += per_day * days_delta
        heating_component = max(per_day - daily_hw_l, 0.0) if curr_hdd > 0 else 0.0
        heating_total += heating_component * days_delta
        total_days += days_delta

    return {
        "total_days": total_days,
        "adjusted_total": adjusted_total,
        "heating_total": heating_total,
        "heat_day_count": heat_day_count,
    }


async def _heating_estimate(
    sf: async_sessionmaker,
    *,
    end_dt: datetime,
    days: int,
    daily_hw_l: float,
    refill_threshold_l: float,
) -> float | None:
    """v1's compute_heating_usage — pure heating component (per-day)
    averaged over days where HDD > 0."""
    start_dt = end_dt - timedelta(days=days + 1)
    readings = await _readings_in_window(sf, start_dt, end_dt)
    if len(readings) < 2:
        return None
    hdd_data = await _hdd_in_window(sf, start_dt, end_dt)
    stats = _usage_stats(readings, hdd_data, daily_hw_l, refill_threshold_l)
    if stats["heat_day_count"] > 0:
        return stats["heating_total"] / stats["heat_day_count"]
    return None


async def _smoothed_recent_daily(
    sf: async_sessionmaker,
    *,
    end_dt: datetime,
    days: int,
    daily_hw_l: float,
    refill_threshold_l: float,
) -> float | None:
    """v1's get_smoothed_daily_usage — per-pair daily averages, HW floor on 0-HDD days."""
    start_dt = end_dt - timedelta(days=days + 1)
    readings = await _readings_in_window(sf, start_dt, end_dt)
    if len(readings) < 2:
        return None
    hdd_data = await _hdd_in_window(sf, start_dt, end_dt)
    daily_usages: list[float] = []
    for prev, curr in zip(readings, readings[1:]):
        used = float(prev.litres_remaining or 0) - float(curr.litres_remaining or 0)
        if used < -refill_threshold_l:
            continue
        if used < 0:
            continue
        prev_dt = parse_local(prev.date)
        curr_dt = parse_local(curr.date)
        if prev_dt is None or curr_dt is None:
            continue
        days_delta = (curr_dt - prev_dt).total_seconds() / 86400
        if days_delta <= 0:
            continue
        per_day = used / days_delta
        curr_day = curr_dt.strftime("%Y-%m-%d")
        if hdd_data.get(curr_day, 0.0) == 0:
            per_day = max(per_day, daily_hw_l)
        daily_usages.append(per_day)
    if not daily_usages:
        return None
    return sum(daily_usages) / len(daily_usages)


async def compute(
    sf: async_sessionmaker, svc: SettingsService
) -> dict[str, Any] | None:
    latest = await _latest_reading(sf)
    earliest = await _earliest_reading(sf)
    if latest is None or earliest is None or latest.date == earliest.date:
        return None

    snap = await _snapshot(svc)
    daily_hw_l = _hot_water_baseline_l_per_day(snap.fuel_rate_l_per_h)

    latest_dt = parse_local(latest.date) or local_now()

    # Resolve the last-refill anchor. The operator's manual log
    # (actual_refill_costs) is authoritative — a real refill that lands in
    # one reading interval gets noise-suppressed and never sets
    # refill_detected='y', so the sensor flag alone leaves the counter
    # months stale. The displayed days_since_refill counts from the refill
    # DATE; the consumption baseline snaps to the first trusted reading
    # at/after it (the post-refill tank level). Fall back to the most recent
    # sensor-detected refill marker only when no manual entry exists.
    anchor = earliest
    anchor_is_refill = False
    refill_dt: datetime | None = None

    manual_refill_date = await _latest_manual_refill_date(sf)
    manual_dt = parse_local(manual_refill_date) if manual_refill_date else None
    if manual_dt is not None and manual_dt <= latest_dt:
        baseline = await _first_trusted_reading_on_or_after(sf, manual_refill_date)
        if baseline is not None and baseline.date != latest.date:
            anchor = baseline
            anchor_is_refill = True
            refill_dt = manual_dt

    if not anchor_is_refill:
        refill = await _latest_refill_anchor(sf)
        if refill is not None and refill.date != latest.date:
            anchor = refill
            anchor_is_refill = True
            refill_dt = parse_local(refill.date)

    anchor_dt = parse_local(anchor.date) or latest_dt
    days_since_anchor = max((latest_dt - anchor_dt).total_seconds() / 86400.0, 0.0)
    # Count days from the refill date itself (manual log or detected marker),
    # not the baseline reading — a refill logged a few days after the physical
    # top-up still reports the operator's date.
    if anchor_is_refill:
        count_from = refill_dt if refill_dt is not None else anchor_dt
        days_since_refill = int(
            max((latest_dt - count_from).total_seconds() / 86400.0, 0.0)
        )
    else:
        days_since_refill = None

    # Total consumption since refill: simple anchor→latest delta (matches v1).
    # The per-pair walker is only used inside the bounded look-back window
    # below for `period_consumption` and the per-day adjusted average.
    total_consumption = max(
        float(anchor.litres_remaining or 0)
        - float(latest.litres_remaining or 0),
        0.0,
    )

    # Bounded look-back for the windowed average — long post-refill windows
    # otherwise let summer's near-zero usage poison the heating-season baseline.
    if anchor_is_refill and days_since_anchor > 0:
        lookback_days = min(
            LOOKBACK_MAX_DAYS,
            max(LOOKBACK_MIN_DAYS, int(days_since_anchor)),
        )
    else:
        lookback_days = LOOKBACK_MIN_DAYS
    analysis_start = max(anchor_dt, latest_dt - timedelta(days=lookback_days))
    analysis_period_days = max(
        (latest_dt - analysis_start).total_seconds() / 86400.0, 1.0
    )

    window_readings = await _readings_in_window(sf, analysis_start, latest_dt)
    window_hdd = await _hdd_in_window(sf, analysis_start, latest_dt)

    # v1's `avg_daily_consumption_l` uses a SIMPLE 7-day delta
    # (earliest_in_7d - latest), clamped at zero or > capacity, divided
    # by 7. The per-pair walker in `_usage_stats` is only used for the
    # heating-only component below — using it for the displayed average
    # over-counts every sensor jitter (200→150→200 reads as +50 L of
    # spurious consumption) and produces wild values like 200 L/day on
    # quiet summer windows.
    weekly_start = latest_dt - timedelta(days=7)
    weekly_readings = await _readings_in_window(sf, weekly_start, latest_dt)
    if len(weekly_readings) >= 2:
        weekly_consumption = (
            float(weekly_readings[0].litres_remaining or 0)
            - float(weekly_readings[-1].litres_remaining or 0)
        )
        if weekly_consumption < 0 or weekly_consumption > snap.capacity_l:
            weekly_consumption = 0.0
        adjusted_daily = max(weekly_consumption / 7.0, daily_hw_l)
    else:
        adjusted_daily = daily_hw_l

    # Recent-7-day smoothed daily, fallback to adjusted.
    recent_daily = await _smoothed_recent_daily(
        sf,
        end_dt=latest_dt,
        days=7,
        daily_hw_l=daily_hw_l,
        refill_threshold_l=snap.refill_threshold_l,
    )
    if recent_daily is None:
        recent_daily = adjusted_daily

    # HDD: cumulative for consumption-per-HDD; today and 7-day-avg for scaling.
    cumulative_hdd_data = await _hdd_in_window(sf, anchor_dt, latest_dt)
    total_hdd = sum(cumulative_hdd_data.values())
    consumption_per_hdd = (
        total_consumption / total_hdd if total_hdd > 0 else 0.0
    )

    today_str = latest_dt.strftime("%Y-%m-%d")
    recent_hdd_data = await _hdd_in_window(
        sf, latest_dt - timedelta(days=7), latest_dt
    )
    today_hdd = recent_hdd_data.get(today_str, 0.0)
    avg_7d_hdd = (
        sum(recent_hdd_data.values()) / len(recent_hdd_data)
        if recent_hdd_data
        else 0.0
    )

    # Upcoming month HDD (next month, same year unless December).
    next_month = latest_dt.month + 1 if latest_dt.month < 12 else 1
    next_year = latest_dt.year + 1 if latest_dt.month == 12 else latest_dt.year
    next_month_key = f"{next_year:04d}-{next_month:02d}-01"
    upcoming_month_hdd = cumulative_hdd_data.get(next_month_key, 0.0)
    if upcoming_month_hdd == 0.0 and cumulative_hdd_data:
        # Fallback: most recent HDD row.
        upcoming_month_hdd = next(iter(reversed(cumulative_hdd_data.values())), 0.0)

    factor = _seasonal_heating_factor(next_month)

    # Heating estimate: blended 7d/long, scaled by today_HDD/avg_7d_HDD,
    # clamped to [MIN_HEATING_L, MAX_HEATING_L]. Zero when today_HDD=0.
    heating_7d = await _heating_estimate(
        sf,
        end_dt=latest_dt,
        days=7,
        daily_hw_l=daily_hw_l,
        refill_threshold_l=snap.refill_threshold_l,
    )
    heating_long = await _heating_estimate(
        sf,
        end_dt=latest_dt,
        days=lookback_days,
        daily_hw_l=daily_hw_l,
        refill_threshold_l=snap.refill_threshold_l,
    )
    if heating_7d is not None and heating_long is not None:
        heating_estimate = (
            heating_7d * HEATING_BLEND_RECENT
            + heating_long * HEATING_BLEND_LONG
        )
    elif heating_7d is not None:
        heating_estimate = heating_7d
    elif heating_long is not None:
        heating_estimate = heating_long
    else:
        heating_estimate = 0.0

    surplus_l = max(recent_daily - daily_hw_l, 0.0)
    heating_l = heating_estimate if heating_estimate > 0 else surplus_l
    if today_hdd == 0:
        heating_l = 0.0
    elif heating_l > 0:
        if avg_7d_hdd > 0:
            scale = _clamp(today_hdd / avg_7d_hdd, HDD_SCALE_MIN, HDD_SCALE_MAX)
            heating_l = heating_l * scale
        heating_l = _clamp(heating_l, MIN_HEATING_L, MAX_HEATING_L)

    estimated_daily_consumption_hdd = max(daily_hw_l + heating_l, daily_hw_l)
    avg_daily_consumption_l = max(adjusted_daily, daily_hw_l)
    avg_daily_consumption_l = max(avg_daily_consumption_l, MIN_CONSUMPTION_L_PER_DAY)

    latest_litres = float(latest.litres_remaining or 0)
    if avg_daily_consumption_l > 0:
        raw_days_remaining = latest_litres / avg_daily_consumption_l
        cap = DAYS_REMAINING_CAP_HDD if today_hdd > 0 else DAYS_REMAINING_CAP_NO_HDD
        estimated_days_remaining = min(raw_days_remaining, cap)
        empty_dt = latest_dt + timedelta(days=estimated_days_remaining)
        empty_date = empty_dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        estimated_days_remaining = 0.0
        empty_date = None

    payload: dict[str, Any] = {
        "latest_reading_date": latest.date,
        "latest_analysis_date": local_now_str(),
        "latest_reading_refill_detected": latest.refill_detected,
        "latest_reading_leak_detected": latest.leak_detected,
        "days_since_refill": days_since_refill,
        "total_consumption_since_refill": round(total_consumption, 1),
        "avg_daily_consumption_l": round(avg_daily_consumption_l, 2),
        "estimated_days_remaining": round(estimated_days_remaining, 1),
        "estimated_empty_date": empty_date,
        "consumption_per_hdd_l": round(consumption_per_hdd, 4),
        "upcoming_month_hdd": round(upcoming_month_hdd, 2),
        "estimated_daily_consumption_hdd_l": round(estimated_daily_consumption_hdd, 2),
        "estimated_daily_hot_water_consumption_l": round(daily_hw_l, 2),
        "estimated_daily_heating_consumption_l": round(heating_l, 2),
        "seasonal_heating_factor": round(factor, 3),
        "remaining_days_empty_hdd": round(estimated_days_remaining, 1),
        "remaining_date_empty_hdd": empty_date,
    }
    return payload


async def _persist(sf: async_sessionmaker, payload: dict[str, Any]) -> None:
    async with sf() as session:
        existing = (
            await session.execute(
                select(AnalysisResult).where(
                    AnalysisResult.latest_reading_date == payload["latest_reading_date"]
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(AnalysisResult(**payload))
        else:
            for k, v in payload.items():
                setattr(existing, k, v)
        await session.commit()


async def run_analysis(
    *,
    sf: async_sessionmaker,
    settings_service: SettingsService,
    publisher: MqttPublisher,
    pubsub: PubSubBus | None = None,
) -> dict[str, Any] | None:
    # Refresh daily hdd_data from per-reading HDD values first — every
    # HDD lookup below keys on YYYY-MM-DD, and nothing else writes the
    # table (KERO-H1). A roll-up failure must not block the analysis;
    # it just runs on whatever hdd_data already holds.
    try:
        await aggregate_daily_hdd(sf)
    except Exception:  # noqa: BLE001
        logger.exception("daily HDD roll-up failed; continuing with existing hdd_data")
    payload = await compute(sf, settings_service)
    if payload is None:
        logger.info("Not enough data for analysis run")
        return None
    await _persist(sf, payload)
    await publisher.publish_analysis(payload)
    if pubsub is not None:
        await pubsub.publish("analysis", payload)
    return payload
