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

from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.clock import local_now, local_now_str, parse_local
from kerotrack.models.cost_analysis import CostAnalysis
from kerotrack.models.hdd import HddDatum
from kerotrack.models.reading import Reading
from kerotrack.models.refill import ActualRefillCost
from kerotrack.models.refill_period import RefillPeriod
from kerotrack.publish.mqtt_publisher import MqttPublisher
from kerotrack.pubsub.bus import PubSubBus
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)


REFILL_MATCH_TOLERANCE_SECONDS = 24 * 3600
MIN_CONSUMPTION_PER_DAY_FALLBACK = 0.1
DEFAULT_EFFICIENCY = 0.85


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


async def _readings_between(
    sf: async_sessionmaker, start: str, end: str, *, inclusive_end: bool = True
) -> list[Reading]:
    async with sf() as session:
        end_clause = Reading.date <= end if inclusive_end else Reading.date < end
        return (
            (
                await session.execute(
                    select(Reading)
                    .where(Reading.date >= start, end_clause)
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
    """v1's calculate_cost_for_period — per-pair walker using PPL-at-time.

    Returns total_cost, total_consumption, average_ppl (pence), daily_cost,
    daily_consumption, weekly_cost, monthly_cost, period_days, estimated_consumption."""
    if len(readings) < 2:
        return {}
    sorted_readings = sorted(readings, key=lambda r: r.date)
    first = sorted_readings[0]
    last = sorted_readings[-1]
    total_consumption = float(first.litres_remaining or 0) - float(last.litres_remaining or 0)
    estimated = False
    if total_consumption <= 0:
        # Tank somehow ended higher — fall back to a tiny synthetic estimate
        # so the period still publishes (matches v1's defensive path).
        days_int = max(int(days), 1)
        total_consumption = days_int * MIN_CONSUMPTION_PER_DAY_FALLBACK
        estimated = True

    total_cost = 0.0
    if estimated:
        ppl = float(last.current_ppl or 0) / 100.0
        total_cost = total_consumption * ppl
    else:
        for prev, curr in zip(sorted_readings, sorted_readings[1:]):
            consumption = (
                float(prev.litres_remaining or 0) - float(curr.litres_remaining or 0)
            )
            if consumption < -refill_threshold_l:
                continue
            if consumption <= 0:
                continue
            ppl = float(prev.current_ppl or 0) / 100.0
            total_cost += consumption * ppl

    days = max(days, 1.0)
    year = parse_local(first.date).year if parse_local(first.date) else local_now().year
    days_in_month = _days_in_month_for(year)

    average_ppl = (
        round((total_cost / total_consumption) * 100, 2)
        if total_consumption > 0
        else float(last.current_ppl or 0)
    )
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
    """Find refill events, pair into periods, walk readings, upsert rows.

    Returns the number of period rows newly inserted or refreshed.
    """
    refill_threshold_l = float(await svc.get("detection.refill_threshold_l"))
    refills = await _all_refill_readings(sf)
    if len(refills) < 2:
        return 0
    actuals = await _all_actual_costs(sf)

    written = 0
    for current, nxt in zip(refills, refills[1:]):
        start_date = current.date
        end_date = nxt.date
        start_dt = parse_local(start_date)
        end_dt = parse_local(end_date)
        if start_dt is None or end_dt is None:
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
        actuals_by_invoice = {
            row.invoice_ref or row.refill_date: row
            for row in (
                await session.execute(select(ActualRefillCost))
            ).scalars().all()
        }

    if not periods:
        return None

    latest = periods[0]
    days_since_refill = 0
    end_dt = parse_local(latest.end_date)
    if end_dt is not None:
        days_since_refill = max((local_now() - end_dt).days, 0)

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
    avg_delivered_energy_per_period_kwh = (
        avg_total_energy_per_period_kwh * energy_efficiency
    )
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
    async with sf() as session:
        existing = (
            await session.execute(
                select(CostAnalysis).where(
                    CostAnalysis.analysis_date == payload["analysis_date"]
                )
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
