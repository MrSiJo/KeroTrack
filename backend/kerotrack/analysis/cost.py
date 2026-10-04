"""Cost analysis port (was `oil_cost_analysis.py`, 2364 lines in v1).

Detects refill periods from `readings`, walks per-pair consumption with the
PPL at each pair (preferred over a flat period-average), prefers
`actual_refill_costs` invoiced amounts when matched within 24h, layers in
HDD-derived metrics and measured (not nameplate) energy efficiency, then
upserts a row per period into `refill_periods`. The final payload publishes
the aggregate `oiltank/cost_analysis` summary.

Output shape locked to spec §3.3 — every key kept, types preserved.

Backlog items addressed here:
- A2: refill_periods is now actually written from detected refills.
- A3: per-period reading-based cost using PPL-at-pair; actual-cost preference.
- A4: cost_per_hdd, consumption_per_hdd, and measured energy_efficiency.
- A5: leap-year-aware days_in_month; weighted historical averages by days.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.clock import local_now, local_now_str, parse_local
from kerotrack.models.cost_analysis import CostAnalysis
from kerotrack.models.hdd import HddDatum
from kerotrack.models.reading import Reading, trusted_readings_clause
from kerotrack.models.refill import ActualRefillCost
from kerotrack.models.refill_period import RefillPeriod
from kerotrack.publish.mqtt_publisher import MqttPublisher
from kerotrack.pubsub.bus import PubSubBus
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)


REFILL_MATCH_TOLERANCE_SECONDS = 24 * 3600
MIN_CONSUMPTION_PER_DAY_FALLBACK = 0.1
DEFAULT_EFFICIENCY = 0.85

# Period boundary rules (spec A7).
# A logged refill date is searched for the real level jump in
# [refill_date - LOOKBACK, refill_date + LOOKAHEAD]: owners often log the
# invoice date, days after the delivery. With no jump, the first trusted
# reading at/after the log date is used only if it is within LOOKAHEAD.
MANUAL_JUMP_LOOKBACK = timedelta(days=14)
MANUAL_JUMP_LOOKAHEAD = timedelta(days=3)
# A sensor refill flag this close to a logged refill defers to the log.
SENSOR_FLAG_MANUAL_EXCLUSION = timedelta(days=7)
# A sensor refill flag must hold its level for this long afterwards.
SENSOR_FLAG_CONFIRM_WINDOW = timedelta(hours=24)
# Boundaries this close together collapse onto the earlier one.
BOUNDARY_DEDUPE_WINDOW = timedelta(days=1)
# Mirrors the `detection.refill_threshold_l` seed default; used only when a
# caller doesn't pass the configured value.
DEFAULT_REFILL_THRESHOLD_L = 100.0
_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _days_in_month_for(year: int) -> float:
    """Calendar-aware days-in-month (366/12 in leap years)."""
    days_in_year = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
    return days_in_year / 12


def _weighted_avg(pairs: Iterable[tuple[float, float]]) -> float:
    """Weighted average. `pairs` = ``(value, weight)``. Returns 0 if total
    weight is 0 — which keeps the previous "flat mean of zero things" behaviour
    out of the response."""
    total_weight = 0.0
    total_value = 0.0
    for value, weight in pairs:
        if weight <= 0:
            continue
        total_value += value * weight
        total_weight += weight
    return total_value / total_weight if total_weight > 0 else 0.0


async def _all_refill_readings(sf: async_sessionmaker) -> list[Reading]:
    async with sf() as session:
        return (
            (
                await session.execute(
                    select(Reading)
                    .where(Reading.refill_detected == "y")
                    .order_by(asc(Reading.date))
                )
            )
            .scalars()
            .all()
        )


async def _first_trusted_reading_at_or_after(
    sf: async_sessionmaker, date_str: str
) -> Reading | None:
    """First non-noise reading at or after ``date_str``: the post-refill
    level a logged refill date anchors to (same query as consumption's
    baseline lookup)."""
    async with sf() as session:
        return (
            await session.execute(
                select(Reading)
                .where(Reading.date >= date_str, trusted_readings_clause())
                .order_by(asc(Reading.date))
                .limit(1)
            )
        ).scalar_one_or_none()


async def _manual_refill_boundary(
    sf: async_sessionmaker, refill_date: str, refill_threshold_l: float
) -> str | None:
    """Boundary timestamp for one logged refill, or None to skip it.

    1. Scan readings in [refill_date - 14 d, refill_date + 3 d], noise
       suppressed rows INCLUDED (a real refill that lands in one interval is
       often noise suppressed), for the first reading that rises more than
       ``refill_threshold_l`` over the last TRUSTED level before it (which
       may sit just before the window) AND whose first trusted reading
       at/after it is still at least ``refill_threshold_l`` above that
       trusted level. Reverting upward spikes and phantom downward dips both
       fail this; scanning continues. The boundary is that first trusted
       reading.
    2. No jump: the first trusted reading at/after ``refill_date``, but only
       when it is within 3 days of it. Log entries that predate the readings
       (or sit in a gap) are skipped rather than collapsing onto whatever
       reading comes next.
    """
    refill_dt = parse_local(refill_date)
    if refill_dt is None:
        return None
    window_start = (refill_dt - MANUAL_JUMP_LOOKBACK).strftime(_TS_FMT)
    window_end_dt = refill_dt + MANUAL_JUMP_LOOKAHEAD
    window_end = window_end_dt.strftime(_TS_FMT)
    async with sf() as session:
        previous_trusted = (
            await session.execute(
                select(Reading.litres_remaining)
                .where(
                    Reading.date < window_start,
                    Reading.litres_remaining.isnot(None),
                    trusted_readings_clause(),
                )
                .order_by(desc(Reading.date))
                .limit(1)
            )
        ).scalar_one_or_none()
        # Every reading in the window (noise rows included: a real refill
        # that lands in one interval is often noise suppressed), tagged with
        # whether it is trusted, via the single shared clause.
        window = (
            await session.execute(
                select(Reading, trusted_readings_clause().label("trusted"))
                .where(
                    Reading.date >= window_start,
                    Reading.date <= window_end,
                    Reading.litres_remaining.isnot(None),
                )
                .order_by(asc(Reading.date))
            )
        ).all()
    if not window:
        return None

    # Rises are measured against the last TRUSTED level, never a noise row:
    # a phantom downward dip followed by a normal trusted reading must not
    # look like a refill. The confirming trusted reading at/after the
    # candidate must also sit at least the threshold above that level, so a
    # reverting upward spike fails too. Failed candidates keep the scan going.
    last_trusted = float(previous_trusted) if previous_trusted is not None else None
    for reading, trusted in window:
        litres = float(reading.litres_remaining)
        if last_trusted is not None and litres - last_trusted > refill_threshold_l:
            post_jump = await _first_trusted_reading_at_or_after(sf, reading.date)
            if (
                post_jump is not None
                and post_jump.litres_remaining is not None
                and float(post_jump.litres_remaining)
                >= last_trusted + refill_threshold_l
            ):
                return post_jump.date
        if trusted:
            last_trusted = litres

    baseline = await _first_trusted_reading_at_or_after(sf, refill_date)
    if baseline is None:
        return None
    baseline_dt = parse_local(baseline.date)
    if baseline_dt is None or baseline_dt > window_end_dt:
        return None
    return baseline.date


async def _trusted_reading_at(sf: async_sessionmaker, date_str: str) -> Reading | None:
    """The trusted reading stamped exactly ``date_str`` (a boundary)."""
    async with sf() as session:
        return (
            await session.execute(
                select(Reading)
                .where(Reading.date == date_str, trusted_readings_clause())
                .limit(1)
            )
        ).scalar_one_or_none()


async def _sensor_flag_holds(
    sf: async_sessionmaker, flagged: Reading, refill_threshold_l: float
) -> bool:
    """True when the level stays up for 24 h after a sensor refill flag.

    Needs at least one trusted reading in the window: a flag on the newest
    reading can't be shown to hold yet, so it waits for the next run (which
    rebuilds the table anyway). Every trusted reading in the window must be
    no more than ``refill_threshold_l`` below the flagged level; flapping
    falls straight back and fails this.
    """
    flagged_dt = parse_local(flagged.date)
    if flagged_dt is None or flagged.litres_remaining is None:
        return False
    window_end = (flagged_dt + SENSOR_FLAG_CONFIRM_WINDOW).strftime(_TS_FMT)
    async with sf() as session:
        following = (
            (
                await session.execute(
                    select(Reading.litres_remaining).where(
                        Reading.date > flagged.date,
                        Reading.date <= window_end,
                        Reading.litres_remaining.isnot(None),
                        trusted_readings_clause(),
                    )
                )
            )
            .scalars()
            .all()
        )
    if not following:
        return False
    floor = float(flagged.litres_remaining) - refill_threshold_l
    return all(float(litres) >= floor for litres in following)


async def _period_boundaries(
    sf: async_sessionmaker,
    refill_threshold_l: float = DEFAULT_REFILL_THRESHOLD_L,
) -> list[str]:
    """Sorted cost period boundary timestamps (spec A7).

    1. Every ``actual_refill_costs.refill_date`` (the operator's log is
       authoritative) maps to a post-refill reading via
       ``_manual_refill_boundary``: the first trusted reading after the real
       level jump near the log date, else the first trusted reading within
       3 days after it. Neither: skipped.
    2. A sensor ``refill_detected == "y"`` reading counts only when no
       logged refill is within 7 days of it, the reading itself is trusted,
       and the level holds for the next 24 h (see ``_sensor_flag_holds``).
       Real refills that were noise suppressed never set the flag, and
       flapping sets it falsely; the log covers both.
    3. When a logged refill predates the earliest trusted reading, that
       reading is also a boundary (it opens the first, partial period).
    4. Boundaries within 1 day of each other collapse onto the earlier.
    """
    actuals = await _all_actual_costs(sf)
    manual_dts: list[datetime] = []
    candidates: set[str] = set()
    for actual in actuals:
        manual_dt = parse_local(actual.refill_date)
        if manual_dt is None:
            continue
        manual_dts.append(manual_dt)
        boundary = await _manual_refill_boundary(
            sf, actual.refill_date, refill_threshold_l
        )
        if boundary is not None:
            candidates.add(boundary)

    async with sf() as session:
        flagged = (
            (
                await session.execute(
                    select(Reading)
                    .where(Reading.refill_detected == "y", trusted_readings_clause())
                    .order_by(asc(Reading.date))
                )
            )
            .scalars()
            .all()
        )
    for reading in flagged:
        flag_dt = parse_local(reading.date)
        if flag_dt is None:
            continue
        if any(
            abs(flag_dt - manual_dt) <= SENSOR_FLAG_MANUAL_EXCLUSION
            for manual_dt in manual_dts
        ):
            continue
        if await _sensor_flag_holds(sf, reading, refill_threshold_l):
            candidates.add(reading.date)

    # A log entry older than every reading means the first reading sits mid
    # period: that period is real, so the first reading opens it.
    if manual_dts:
        earliest = await _first_trusted_reading_at_or_after(sf, "")
        earliest_dt = parse_local(earliest.date) if earliest is not None else None
        if earliest is not None and earliest_dt is not None and any(
            manual_dt < earliest_dt for manual_dt in manual_dts
        ):
            candidates.add(earliest.date)

    boundaries: list[str] = []
    last_dt: datetime | None = None
    for date_str in sorted(candidates):
        dt = parse_local(date_str)
        if dt is None:
            continue
        if last_dt is not None and dt - last_dt <= BOUNDARY_DEDUPE_WINDOW:
            continue
        boundaries.append(date_str)
        last_dt = dt
    return boundaries


async def _readings_between(
    sf: async_sessionmaker, start: str, end: str, *, inclusive_end: bool = True
) -> list[Reading]:
    """Window readings between two timestamps for cost walkers.

    Excludes rows tagged ``noise_suppressed`` in ``raw_flags`` — the
    per-pair PPL walker would otherwise treat a multipath spike's bad
    litres value as real consumption when the next reading reverts.
    """
    async with sf() as session:
        end_clause = Reading.date <= end if inclusive_end else Reading.date < end
        return (
            (
                await session.execute(
                    select(Reading)
                    .where(
                        Reading.date >= start,
                        end_clause,
                        trusted_readings_clause(),
                    )
                    .order_by(asc(Reading.date))
                )
            )
            .scalars()
            .all()
        )


async def _hdd_between(sf: async_sessionmaker, start: str, end: str) -> dict[str, float]:
    start_day = start.split(" ")[0]
    end_day = end.split(" ")[0]
    async with sf() as session:
        rows = (
            (
                await session.execute(
                    select(HddDatum)
                    .where(HddDatum.date >= start_day, HddDatum.date <= end_day)
                    .order_by(asc(HddDatum.date))
                )
            )
            .scalars()
            .all()
        )
    return {r.date: float(r.hdd or 0) for r in rows}


async def _last_reading_before(sf: async_sessionmaker, when: str) -> Reading | None:
    async with sf() as session:
        return (
            await session.execute(
                select(Reading)
                .where(Reading.date < when, Reading.litres_remaining.isnot(None))
                .order_by(desc(Reading.date))
                .limit(1)
            )
        ).scalar_one_or_none()


async def _all_actual_costs(sf: async_sessionmaker) -> list[ActualRefillCost]:
    async with sf() as session:
        return (
            (await session.execute(select(ActualRefillCost))).scalars().all()
        )


def _match_actual_cost(
    refill_date: str, actuals: list[ActualRefillCost]
) -> ActualRefillCost | None:
    """v1's find_matching_actual_cost — exact match preferred, else within 24h."""
    refill_dt = parse_local(refill_date)
    if refill_dt is None:
        return None
    for cost in actuals:
        cost_dt = parse_local(cost.refill_date)
        if cost_dt is not None and cost_dt == refill_dt:
            return cost
    for cost in actuals:
        cost_dt = parse_local(cost.refill_date)
        if cost_dt is None:
            continue
        if abs((cost_dt - refill_dt).total_seconds()) <= REFILL_MATCH_TOLERANCE_SECONDS:
            return cost
    return None


def _avg_efficiency_decimal(readings: list[Reading]) -> float | None:
    """Mean of seasonal_efficiency in the period, normalised to 0-1.

    v1 stored it as a percentage (e.g. 92.0); newer rows may already be
    decimals — we accept both and never produce a value outside (0, 1]."""
    values = [r.seasonal_efficiency for r in readings if r.seasonal_efficiency is not None]
    if not values:
        return None
    avg = sum(values) / len(values)
    if avg > 1:
        avg = avg / 100.0
    return avg if 0 < avg <= 1 else None


def _per_pair_cost(
    readings: list[Reading], days: float, refill_threshold_l: float
) -> dict[str, float]:
    """Net-consumption × time-weighted-average-PPL period cost.

    Per-pair cost summing breaks badly on dense ingest data: every bit
    of sensor jitter that produces a positive momentary drop gets
    counted, so a window with 502 L net consumption and 8 000 broadcast
    pairs sums to ~4 300 L of phantom positive deltas (~8x cost
    inflation). This formulation is mathematically correct: total cost
    is the actual net litres consumed × the average pence-per-litre
    weighted by the duration each PPL value was in force.

    `refill_threshold_l` is retained on the signature for compatibility
    but no longer needed — net consumption inherently ignores
    intermediate refills.
    """
    _ = refill_threshold_l  # kept for callers + future use
    if len(readings) < 2:
        return {}
    sorted_readings = sorted(readings, key=lambda r: r.date)
    first = sorted_readings[0]
    last = sorted_readings[-1]
    total_consumption = (
        float(first.litres_remaining or 0) - float(last.litres_remaining or 0)
    )
    estimated = False
    if total_consumption <= 0:
        # Tank somehow ended higher — fall back to a tiny synthetic estimate
        # so the period still publishes (matches v1's defensive path).
        days_int = max(int(days), 1)
        total_consumption = days_int * MIN_CONSUMPTION_PER_DAY_FALLBACK
        estimated = True

    if estimated:
        ppl_pence = float(last.current_ppl or 0)
        total_cost = total_consumption * (ppl_pence / 100.0)
        average_ppl = round(ppl_pence, 2)
    else:
        weighted_ppl_days = 0.0
        total_days = 0.0
        for prev, curr in zip(sorted_readings, sorted_readings[1:]):
            prev_dt = parse_local(prev.date)
            curr_dt = parse_local(curr.date)
            if prev_dt is None or curr_dt is None:
                continue
            delta_days = (curr_dt - prev_dt).total_seconds() / 86400.0
            if delta_days <= 0:
                continue
            ppl_pence = float(prev.current_ppl or 0)
            if ppl_pence <= 0:
                continue
            weighted_ppl_days += ppl_pence * delta_days
            total_days += delta_days
        if total_days > 0:
            average_ppl = weighted_ppl_days / total_days
        else:
            average_ppl = float(last.current_ppl or 0)
        total_cost = total_consumption * (average_ppl / 100.0)
        average_ppl = round(average_ppl, 2)

    days = max(days, 1.0)
    year = parse_local(first.date).year if parse_local(first.date) else local_now().year
    days_in_month = _days_in_month_for(year)

    return {
        "total_cost": round(total_cost, 2),
        "total_consumption": round(total_consumption, 2),
        "average_ppl": average_ppl,
        "daily_cost": round(total_cost / days, 2),
        "daily_consumption": round(total_consumption / days, 2),
        "weekly_cost": round((total_cost / days) * 7, 2),
        "monthly_cost": round((total_cost / days) * days_in_month, 2),
        "period_days": days,
        "estimated_consumption": estimated,
    }


async def _detect_periods(
    sf: async_sessionmaker, svc: SettingsService
) -> int:
    """Pair period boundaries into periods, walk readings, upsert rows,
    then delete ``refill_periods`` rows that no longer match a boundary pair.

    Boundaries come from the refill log first (``_period_boundaries``).
    Returns the number of period rows newly inserted or refreshed.
    """
    refill_threshold_l = float(await svc.get("detection.refill_threshold_l"))
    boundaries = await _period_boundaries(sf, refill_threshold_l)
    if len(boundaries) < 2:
        # No pairs computed: leave the table alone rather than wipe it.
        return 0
    actuals = await _all_actual_costs(sf)

    written = 0
    computed_pairs: set[tuple[str, str]] = set()
    for start_date, end_date in zip(boundaries, boundaries[1:]):
        computed_pairs.add((start_date, end_date))
        start_dt = parse_local(start_date)
        end_dt = parse_local(end_date)
        if start_dt is None or end_dt is None:
            continue
        current = await _trusted_reading_at(sf, start_date)
        nxt = await _trusted_reading_at(sf, end_date)
        if current is None or nxt is None:
            continue
        days = max((end_dt - start_dt).days, 1)

        # Walk readings INSIDE the period (exclude the trailing refill row
        # so the per-pair walker doesn't see the post-refill jump as a
        # negative consumption). v1 did the same via pre_refill_reading.
        readings = await _readings_between(
            sf, start_date, end_date, inclusive_end=False
        )
        hdd_data = await _hdd_between(sf, start_date, end_date)

        # Reading-based cost via per-pair walker (PPL-at-time).
        cost_metrics = _per_pair_cost(readings, days, refill_threshold_l)
        if not cost_metrics:
            # Not enough readings to value the period — record a minimal row
            # so the period still surfaces.
            cost_metrics = {
                "total_cost": 0.0,
                "total_consumption": 0.0,
                "average_ppl": 0.0,
                "daily_cost": 0.0,
                "daily_consumption": 0.0,
                "weekly_cost": 0.0,
                "monthly_cost": 0.0,
                "period_days": days,
                "estimated_consumption": True,
            }

        # Pre-refill reading just before the next refill to validate consumption.
        pre_refill = await _last_reading_before(sf, end_date)
        sensor_consumption = None
        if pre_refill is not None:
            sensor_consumption = (
                float(current.litres_remaining or 0)
                - float(pre_refill.litres_remaining or 0)
            )

        # HDD metrics.
        total_hdd = sum(hdd_data.values())
        cost_per_hdd = (
            cost_metrics["total_cost"] / total_hdd if total_hdd > 0 else 0.0
        )
        consumption_per_hdd = (
            cost_metrics["total_consumption"] / total_hdd if total_hdd > 0 else 0.0
        )

        # Refill bookkeeping — actual invoice preferred when matched within 24h.
        actual = _match_actual_cost(end_date, actuals)
        if actual is not None:
            refill_amount = actual.actual_volume_litres or 0.0
            refill_ppl = actual.actual_ppl or 0.0
            refill_cost = actual.total_cost or 0.0
            refill_invoice = actual.invoice_ref or ""
            refill_notes = actual.notes or ""
            used_actual = 1
        else:
            # Sensor-derived: fill amount = post-refill - pre-refill litres.
            refill_amount = (
                float(nxt.litres_remaining or 0)
                - float(pre_refill.litres_remaining or 0)
                if pre_refill is not None
                else 0.0
            )
            refill_amount = max(refill_amount, 0.0)
            refill_ppl = float(nxt.current_ppl or 0)
            refill_cost = round(refill_amount * (refill_ppl / 100.0), 2)
            refill_invoice = ""
            refill_notes = ""
            used_actual = 0

        period = {
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
            "total_consumption": cost_metrics["total_consumption"],
            "average_ppl": cost_metrics["average_ppl"],
            "total_cost": cost_metrics["total_cost"],
            "daily_cost": cost_metrics["daily_cost"],
            "weekly_cost": cost_metrics["weekly_cost"],
            "monthly_cost": cost_metrics["monthly_cost"],
            "refill_amount_liters": round(refill_amount, 2),
            "refill_ppl": round(refill_ppl, 2),
            "refill_cost": round(refill_cost, 2),
            "refill_invoice": refill_invoice,
            "refill_notes": refill_notes,
            "used_actual_cost": used_actual,
            "analysis_date": local_now_str(),
            "total_hdd": round(total_hdd, 2),
            "cost_per_hdd": round(cost_per_hdd, 4),
            "consumption_per_hdd": round(consumption_per_hdd, 4),
        }

        async with sf() as session:
            existing = (
                await session.execute(
                    select(RefillPeriod).where(
                        RefillPeriod.start_date == start_date,
                        RefillPeriod.end_date == end_date,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(RefillPeriod(**period))
            else:
                for k, v in period.items():
                    setattr(existing, k, v)
            await session.commit()
        written += 1

        if sensor_consumption is not None and sensor_consumption < 0:
            logger.debug(
                "Sensor consumption negative (%.2f) between %s and %s — period kept anyway",
                sensor_consumption,
                start_date,
                end_date,
            )

    # Rows from earlier boundary sets (e.g. a sensor-only false refill) no
    # longer match any pair: delete them so the table is rebuilt each run.
    # Only once at least one period was actually written, so a run that
    # could value nothing never empties the table.
    if written == 0:
        return 0
    async with sf() as session:
        stale = [
            row
            for row in (await session.execute(select(RefillPeriod))).scalars().all()
            if (row.start_date, row.end_date) not in computed_pairs
        ]
        for row in stale:
            await session.delete(row)
        await session.commit()
    if stale:
        logger.info("Deleted %d stale refill period(s)", len(stale))

    return written


async def _measured_efficiency(sf: async_sessionmaker) -> float | None:
    """Return the average measured efficiency (0-1) across all readings, or
    None if no measurement is available."""
    async with sf() as session:
        rows = (
            (
                await session.execute(
                    select(Reading.seasonal_efficiency).where(
                        Reading.seasonal_efficiency.isnot(None)
                    )
                )
            )
            .scalars()
            .all()
        )
    if not rows:
        return None
    avg = sum(rows) / len(rows)
    if avg > 1:
        avg = avg / 100.0
    return avg if 0 < avg <= 1 else None


async def compute(
    sf: async_sessionmaker, svc: SettingsService
) -> dict[str, Any] | None:
    async with sf() as session:
        periods = (
            await session.execute(
                select(RefillPeriod).order_by(desc(RefillPeriod.end_date))
            )
        ).scalars().all()
        refill_log_dates = (
            await session.execute(select(ActualRefillCost.refill_date))
        ).scalars().all()

    if not periods:
        return None

    latest = periods[0]
    now = local_now()

    def _whole_days_since(when: datetime | None) -> int | None:
        if when is None:
            return None
        return int(max((now - when).total_seconds() / 86400.0, 0.0))

    # A8: days_since_period_end is the old meaning (from the latest period's
    # end); days_since_refill now matches oiltank/analysis: days from the
    # last logged refill date, else the latest accepted period boundary.
    days_since_period_end = _whole_days_since(parse_local(latest.end_date))
    manual_dts = [
        dt
        for dt in (parse_local(date_str) for date_str in refill_log_dates)
        if dt is not None
    ]
    if manual_dts:
        refill_dt: datetime | None = max(manual_dts)
    else:
        refill_threshold_l = float(await svc.get("detection.refill_threshold_l"))
        boundaries = await _period_boundaries(sf, refill_threshold_l)
        refill_dt = parse_local(boundaries[-1] if boundaries else latest.end_date)
    days_since_refill = _whole_days_since(refill_dt)
    if days_since_refill is None:
        days_since_refill = days_since_period_end or 0

    # Weighted-by-days historical averages (A5).
    period_days_pairs = [(p.total_cost or 0.0, p.days or 0) for p in periods]
    consumption_pairs = [(p.total_consumption or 0.0, p.days or 0) for p in periods]
    daily_cost_pairs = [(p.daily_cost or 0.0, p.days or 0) for p in periods]
    cost_per_hdd_pairs = [(p.cost_per_hdd or 0.0, p.days or 0) for p in periods]
    consumption_per_hdd_pairs = [
        (p.consumption_per_hdd or 0.0, p.days or 0) for p in periods
    ]

    avg_period_cost = _weighted_avg(period_days_pairs)
    avg_period_consumption = _weighted_avg(consumption_pairs)
    avg_daily_cost = _weighted_avg(daily_cost_pairs)
    avg_cost_per_hdd = _weighted_avg(cost_per_hdd_pairs)
    avg_consumption_per_hdd = _weighted_avg(consumption_per_hdd_pairs)

    # Energy efficiency: measured (A4) preferred, fall back to nameplate.
    measured = await _measured_efficiency(sf)
    if measured is None:
        nameplate = float(await svc.get("boiler.efficiency_pct")) / 100.0
        energy_efficiency = nameplate if 0 < nameplate <= 1 else DEFAULT_EFFICIENCY
    else:
        energy_efficiency = measured

    # kWh metrics derived from settings + weighted averages.
    kwh_per_l = float(await svc.get("analysis.kwh_per_liter"))
    avg_total_energy_per_period_kwh = avg_period_consumption * kwh_per_l
    avg_cost_per_kwh = (
        avg_period_cost / avg_total_energy_per_period_kwh
        if avg_total_energy_per_period_kwh > 0
        else 0.0
    )
    # Daily delivered energy across the weighted historical average.
    avg_daily_energy_kwh = (
        avg_daily_cost / avg_cost_per_kwh if avg_cost_per_kwh > 0 else 0.0
    )
    # Cost per useful kWh (heat-unit) — same as cost_per_useful_kwh in v1.
    avg_cost_per_heat_unit = (
        avg_cost_per_kwh / energy_efficiency if energy_efficiency > 0 else 0.0
    )

    payload = {
        "analysis_date": local_now_str(),
        "latest_period_start": latest.start_date,
        "latest_period_end": latest.end_date,
        "latest_period_days": latest.days or 0,
        "latest_refill_amount": latest.refill_amount_liters or 0.0,
        "latest_refill_cost": latest.refill_cost or 0.0,
        "latest_refill_ppl": latest.refill_ppl or 0.0,
        "latest_total_consumption": latest.total_consumption or 0.0,
        "latest_total_cost": latest.total_cost or 0.0,
        "latest_daily_cost": latest.daily_cost or 0.0,
        "latest_weekly_cost": latest.weekly_cost or 0.0,
        "latest_monthly_cost": latest.monthly_cost or 0.0,
        "days_since_refill": days_since_refill,
        "days_since_period_end": days_since_period_end,
        "avg_period_cost": round(avg_period_cost, 2),
        "avg_period_consumption": round(avg_period_consumption, 1),
        "avg_daily_cost": round(avg_daily_cost, 2),
        "avg_weekly_cost": round(avg_daily_cost * 7, 2),
        "avg_monthly_cost": round(
            avg_daily_cost * _days_in_month_for(local_now().year), 2
        ),
        "avg_annual_cost": round(avg_daily_cost * 365, 2),
        "avg_cost_per_hdd": round(avg_cost_per_hdd, 4),
        "avg_consumption_per_hdd": round(avg_consumption_per_hdd, 4),
        "avg_cost_per_kwh": round(avg_cost_per_kwh, 4),
        "avg_daily_energy_kwh": round(avg_daily_energy_kwh, 2),
        "avg_cost_per_heat_unit": round(avg_cost_per_heat_unit, 4),
        "total_refill_periods": len(periods),
        "percentage_with_actual_data": round(
            100.0 * sum(1 for p in periods if p.used_actual_cost) / max(len(periods), 1),
            1,
        ),
        "energy_efficiency": round(energy_efficiency, 4),
    }
    payload["analysis_data"] = json.dumps({"period_count": len(periods)})
    return payload


async def _persist(sf: async_sessionmaker, payload: dict[str, Any]) -> None:
    """Upsert keyed on the analysis DAY, not the full timestamp.

    `analysis_date` is second-resolution, so matching on the exact value
    inserted a fresh row on every scheduled/manual run — an append-only
    table of near-duplicates (KERO-L5). Re-runs on the same day now update
    that day's row in place.
    """
    day = str(payload["analysis_date"])[:10]
    async with sf() as session:
        existing = (
            await session.execute(
                select(CostAnalysis)
                .where(func.substr(CostAnalysis.analysis_date, 1, 10) == day)
                .order_by(desc(CostAnalysis.analysis_date))
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(CostAnalysis(**payload))
        else:
            for k, v in payload.items():
                setattr(existing, k, v)
        await session.commit()


async def run_cost_analysis(
    *,
    sf: async_sessionmaker,
    settings_service: SettingsService,
    publisher: MqttPublisher,
    pubsub: PubSubBus | None = None,
) -> dict[str, Any] | None:
    written = await _detect_periods(sf, settings_service)
    if written:
        logger.info("Detected/refreshed %d refill period(s)", written)

    payload = await compute(sf, settings_service)
    if payload is None:
        logger.info("No refill periods — skipping cost analysis")
        return None
    await _persist(sf, payload)
    await publisher.publish_costanalysis(payload)
    if pubsub is not None:
        await pubsub.publish("cost_analysis", payload)
    return payload
