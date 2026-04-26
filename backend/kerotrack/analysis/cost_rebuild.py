"""One-shot historical cost rebuild — backfills `monthly_avg_ppl` from
ONS data, then re-runs `_detect_periods` using a PPL resolver that
prefers (1) live-changing sensor values, (2) ONS monthly averages, or
(3) linear interpolation between real anchors.

This module is **not part of the live ingest path**. It runs from
``kerotrack rebuild-costs`` and never modifies anything unless invoked
with ``--apply``. New deployments don't need it; this fixes the
historical PPL data for this specific instance where the
HomeFuelsDirect scrape was stuck for ~7 months in 2025.

Algorithm (per reading-pair):

  1. If the sensor `current_ppl` was changing inside a STUCK_THRESHOLD-day
     window around the pair, trust it. Live data is fine.
  2. Else look up the ONS month for that pair. Use the ONS value.
  3. Else the pair sits in an ONS gap (the series ends Jan 2025 and is
     published with a ~15-month lag). Linearly interpolate between the
     two nearest real anchors:
         - last ONS month available
         - any actual_refill_costs row date
         - first reliable post-fix sensor reading (the BoilerJuice
           scrape only started returning real values ~2026-04-26)

Spurious migrated period rows (start=2025-04-25 + monthly first-of-month
endpoints at 06:18:02, all sharing refill_ppl=50.99) are removed before
re-detection so v1's bogus checkpoints don't survive into the corrected
data.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import asc, delete, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.cost import (
    _all_actual_costs,
    _all_refill_readings,
    _hdd_between,
    _last_reading_before,
    _match_actual_cost,
    _readings_between,
)
from kerotrack.clock import local_now_str, parse_local
from kerotrack.models.monthly_ppl import MonthlyPpl
from kerotrack.models.reading import Reading
from kerotrack.models.refill import ActualRefillCost
from kerotrack.models.refill_period import RefillPeriod
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)


# A sensor PPL stuck at the same value for >= this many days is treated
# as a broken-scrape reading; we substitute a defensible value. Real
# kerosene prices move within days under normal market conditions, so
# anything stuck multi-week is almost certainly wrong.
STUCK_THRESHOLD_DAYS = 14

# v1's analysis cron used to write a refill_period row each month with
# start=2025-04-25 10:03:43 and end=YYYY-MM-01 06:18:02. None of those
# are real refills; we strip them before re-detection.
SPURIOUS_PERIOD_START = "2025-04-25 10:03:43"


_MONTH_NAMES = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_ons_csv(path: Path) -> list[tuple[str, float]]:
    """Parse the ONS RPI Heating Oil series CSV.

    Returns a list of ``(YYYY-MM, ppl_pence)`` tuples for every monthly
    row. Annual + quarterly rows are ignored. The raw integer value is
    stored as pence per 1000 L; we divide by 1000 to get pence per litre.

    Tolerates the ONS preamble (``Title``, ``CDID``, etc.) and the gap
    rows after annual and quarterly sections.
    """
    if not path.exists():
        return []
    out: list[tuple[str, float]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) != 2:
                continue
            label, raw = row[0].strip(), row[1].strip()
            if not raw:
                continue
            parts = label.split()
            # Monthly rows look like "2025 JAN".
            if len(parts) != 2:
                continue
            year_str, mon_str = parts
            month_num = _MONTH_NAMES.get(mon_str.upper())
            if month_num is None or not year_str.isdigit():
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            ppl = value / 1000.0  # pence per 1000 L → pence per litre
            out.append((f"{int(year_str):04d}-{month_num:02d}", ppl))
    return out


async def import_ons_csv(
    sf: async_sessionmaker, *, csv_path: Path, source: str = "ONS RPI MM23/KJ5U"
) -> int:
    """Upsert ONS monthly rows into `monthly_avg_ppl`. Returns row count."""
    rows = parse_ons_csv(csv_path)
    if not rows:
        return 0
    async with sf() as session:
        existing = {
            r[0]
            for r in (
                await session.execute(select(MonthlyPpl.month))
            ).all()
        }
        for month, ppl in rows:
            if month in existing:
                # Update existing.
                stored = (
                    await session.execute(
                        select(MonthlyPpl).where(MonthlyPpl.month == month)
                    )
                ).scalar_one()
                stored.ppl = ppl
                stored.source = source
            else:
                await session.execute(
                    insert(MonthlyPpl).values(month=month, ppl=ppl, source=source)
                )
        await session.commit()
    return len(rows)


# ---------------------------------------------------------- PPL resolver


async def _ons_lookup(sf: async_sessionmaker) -> dict[str, float]:
    async with sf() as session:
        rows = (await session.execute(select(MonthlyPpl))).scalars().all()
    return {r.month: float(r.ppl) for r in rows}


async def _first_reliable_sensor_ppl(
    sf: async_sessionmaker,
) -> tuple[datetime, float] | None:
    """The first sensor reading after the BoilerJuice scrape fix.

    Heuristic: find the earliest reading whose `current_ppl` differs
    from the immediately-previous reading by ≥ 5p (i.e. the scrape just
    started returning real values again). Falls back to the latest
    reading if the heuristic doesn't match.
    """
    async with sf() as session:
        rows = (
            (
                await session.execute(
                    select(Reading)
                    .where(Reading.current_ppl.isnot(None), Reading.current_ppl > 0)
                    .order_by(asc(Reading.date))
                )
            )
            .scalars()
            .all()
        )
    if not rows:
        return None
    prev_ppl = float(rows[0].current_ppl or 0)
    for r in rows[1:]:
        ppl = float(r.current_ppl or 0)
        if ppl <= 0:
            continue
        if abs(ppl - prev_ppl) >= 5.0:
            dt = parse_local(r.date)
            if dt is not None:
                return (dt, ppl)
        prev_ppl = ppl
    # No big jumps anywhere — fall back to the latest reading.
    last = rows[-1]
    dt = parse_local(last.date)
    if dt is None or last.current_ppl is None:
        return None
    return (dt, float(last.current_ppl))


def _is_sensor_stuck(
    readings_window: Sequence[Reading], target_dt: datetime
) -> bool:
    """True when sensor `current_ppl` doesn't change for ≥ STUCK_THRESHOLD
    around `target_dt`."""
    distinct: set[float] = set()
    earliest: datetime | None = None
    latest: datetime | None = None
    for r in readings_window:
        ppl = r.current_ppl
        if ppl is None or ppl <= 0:
            continue
        rdt = parse_local(r.date)
        if rdt is None:
            continue
        distinct.add(round(float(ppl), 2))
        earliest = rdt if earliest is None or rdt < earliest else earliest
        latest = rdt if latest is None or rdt > latest else latest
    if earliest is None or latest is None:
        return True  # no data at all → can't trust sensor
    span_days = (latest - earliest).total_seconds() / 86400.0
    # Stuck when there's only one (or zero) distinct values across a
    # window that already covers ≥ STUCK_THRESHOLD_DAYS.
    return len(distinct) <= 1 and span_days >= STUCK_THRESHOLD_DAYS


def _interpolate(
    target_dt: datetime,
    anchors: list[tuple[datetime, float]],
) -> float | None:
    """Linear interpolation between the nearest two anchors, or simply
    the value of the closest anchor when target is outside the range."""
    if not anchors:
        return None
    sorted_anchors = sorted(anchors, key=lambda a: a[0])
    if target_dt <= sorted_anchors[0][0]:
        return sorted_anchors[0][1]
    if target_dt >= sorted_anchors[-1][0]:
        return sorted_anchors[-1][1]
    for (t1, p1), (t2, p2) in zip(sorted_anchors, sorted_anchors[1:]):
        if t1 <= target_dt <= t2:
            span = (t2 - t1).total_seconds()
            if span <= 0:
                return p1
            frac = (target_dt - t1).total_seconds() / span
            return p1 + (p2 - p1) * frac
    return sorted_anchors[-1][1]


class PplResolver:
    """Resolves a defensible PPL for a reading at a given timestamp.

    Built once from a snapshot of `monthly_avg_ppl`,
    `actual_refill_costs`, and the first-reliable-sensor reading. Then
    queried per-pair by `_per_pair_cost_with_resolver`.
    """

    def __init__(
        self,
        *,
        ons: dict[str, float],
        actuals: list[ActualRefillCost],
        first_reliable: tuple[datetime, float] | None,
    ) -> None:
        self._ons = ons
        # Build interpolation anchors: every ONS month at mid-month, every
        # actual refill date, the first-reliable sensor reading. Strip
        # timezone info so naive (ONS-derived) and aware (parse_local)
        # datetimes can sort against each other.
        anchors: list[tuple[datetime, float]] = []
        for month_str, ppl in ons.items():
            year, mon = month_str.split("-")
            anchors.append(
                (datetime(int(year), int(mon), 15, 0, 0, 0), ppl)
            )
        for actual in actuals:
            adt = parse_local(actual.refill_date)
            if adt is not None and actual.actual_ppl is not None:
                anchors.append(
                    (adt.replace(tzinfo=None), float(actual.actual_ppl))
                )
        if first_reliable is not None:
            fdt, fppl = first_reliable
            anchors.append((fdt.replace(tzinfo=None), fppl))
        self._anchors = anchors

    def resolve(
        self,
        *,
        target_dt: datetime,
        sensor_ppl: float | None,
        sensor_window: Sequence[Reading],
    ) -> tuple[float, str]:
        """Return ``(resolved_ppl, source_tag)`` for the pair at target_dt.

        source_tag is one of: ``sensor_live``, ``ons_month``,
        ``interpolated``, ``zero``.
        """
        # 1. Live-moving sensor reading wins.
        if (
            sensor_ppl is not None
            and sensor_ppl > 0
            and not _is_sensor_stuck(sensor_window, target_dt)
        ):
            return sensor_ppl, "sensor_live"

        # 2. ONS month.
        month_key = target_dt.strftime("%Y-%m")
        if month_key in self._ons:
            return self._ons[month_key], "ons_month"

        # 3. Interpolation. Strip tz from target so it compares cleanly
        # against the naive anchors above.
        naive_target = (
            target_dt.replace(tzinfo=None)
            if target_dt.tzinfo is not None
            else target_dt
        )
        interp = _interpolate(naive_target, self._anchors)
        if interp is not None and interp > 0:
            return interp, "interpolated"

        return 0.0, "zero"


def _per_pair_cost_with_resolver(
    readings: list[Reading],
    days: float,
    refill_threshold_l: float,
    *,
    resolver: PplResolver,
    sensor_window: list[Reading],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Net-consumption × time-weighted-average-PPL cost.

    Per-pair cost summing breaks badly on dense ingest data: every bit
    of sensor jitter that produces a positive momentary drop gets
    counted, so a window with 502 L net consumption and 8 000 broadcast
    pairs sums to ~4 300 L of phantom positive deltas (~8x inflation).

    This formulation is mathematically correct: total cost is the actual
    net litres consumed multiplied by the average pence-per-litre that
    applied across the window, weighted by the duration each PPL value
    was in force. Returns (metrics, source_counts).
    """
    sources: dict[str, int] = {
        "sensor_live": 0,
        "ons_month": 0,
        "interpolated": 0,
        "zero": 0,
    }
    if len(readings) < 2:
        return {}, sources
    sorted_readings = sorted(readings, key=lambda r: r.date)
    first = sorted_readings[0]
    last = sorted_readings[-1]
    total_consumption = (
        float(first.litres_remaining or 0) - float(last.litres_remaining or 0)
    )
    if total_consumption <= 0:
        return {}, sources

    # Time-weighted PPL across the period — each pair contributes its
    # PPL × the days_delta it was in force for.
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
        ppl, src = resolver.resolve(
            target_dt=prev_dt,
            sensor_ppl=float(prev.current_ppl) if prev.current_ppl else None,
            sensor_window=sensor_window,
        )
        sources[src] += 1
        weighted_ppl_days += ppl * delta_days
        total_days += delta_days

    if total_days <= 0:
        return {}, sources
    average_ppl = weighted_ppl_days / total_days
    total_cost = total_consumption * (average_ppl / 100.0)

    days = max(days, 1.0)
    return {
        "total_cost": round(total_cost, 2),
        "total_consumption": round(total_consumption, 2),
        "average_ppl": round(average_ppl, 2),
        "daily_cost": round(total_cost / days, 2),
        "weekly_cost": round((total_cost / days) * 7, 2),
        "monthly_cost": round((total_cost / days) * 30.44, 2),
        "period_days": days,
    }, sources


# ------------------------------------------------------------- top-level


async def rebuild_periods(
    sf: async_sessionmaker,
    svc: SettingsService,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Re-detect refill periods from sensor refills using the PPL resolver.

    When ``apply=False`` (default), nothing is written — the function
    just returns a report dict for human inspection. When ``apply=True``,
    spurious migrated rows are deleted and the new computed rows are
    upserted.
    """
    refill_threshold_l = float(await svc.get("detection.refill_threshold_l"))

    # Snapshot inputs for the resolver.
    ons = await _ons_lookup(sf)
    actuals = await _all_actual_costs(sf)
    first_reliable = await _first_reliable_sensor_ppl(sf)
    resolver = PplResolver(
        ons=ons,
        actuals=actuals,
        first_reliable=first_reliable,
    )

    # Snapshot existing periods (so we can show before/after).
    async with sf() as session:
        existing_periods = (
            await session.execute(
                select(RefillPeriod).order_by(asc(RefillPeriod.start_date))
            )
        ).scalars().all()
        existing_payloads = [
            {c: getattr(p, c) for c in p.__table__.columns.keys()}
            for p in existing_periods
        ]

    spurious = [
        p for p in existing_payloads
        if p["start_date"] == SPURIOUS_PERIOD_START
        and isinstance(p["end_date"], str)
        and p["end_date"].endswith("-01 06:18:02")
        and p["end_date"] != SPURIOUS_PERIOD_START
    ]

    refills = await _all_refill_readings(sf)
    detected: list[dict[str, Any]] = []
    aggregate_sources: dict[str, int] = {
        "sensor_live": 0,
        "ons_month": 0,
        "interpolated": 0,
        "zero": 0,
    }

    for current, nxt in zip(refills, refills[1:]):
        start_date = current.date
        end_date = nxt.date
        start_dt = parse_local(start_date)
        end_dt = parse_local(end_date)
        if start_dt is None or end_dt is None:
            continue
        days = max((end_dt - start_dt).days, 1)

        readings = await _readings_between(
            sf, start_date, end_date, inclusive_end=False
        )
        hdd_data = await _hdd_between(sf, start_date, end_date)

        # Sensor-stuck detection uses a window of ±STUCK_THRESHOLD_DAYS around
        # each pair, scoped to the period — period_readings IS that window.
        cost_metrics, sources = _per_pair_cost_with_resolver(
            readings,
            days,
            refill_threshold_l,
            resolver=resolver,
            sensor_window=readings,
        )
        for k, v in sources.items():
            aggregate_sources[k] += v

        if not cost_metrics:
            continue

        pre_refill = await _last_reading_before(sf, end_date)
        total_hdd = sum(hdd_data.values())
        cost_per_hdd = (
            cost_metrics["total_cost"] / total_hdd if total_hdd > 0 else 0.0
        )
        consumption_per_hdd = (
            cost_metrics["total_consumption"] / total_hdd if total_hdd > 0 else 0.0
        )

        actual = _match_actual_cost(end_date, actuals)
        if actual is not None:
            refill_amount = actual.actual_volume_litres or 0.0
            refill_ppl = actual.actual_ppl or 0.0
            refill_cost = actual.total_cost or 0.0
            refill_invoice = actual.invoice_ref or ""
            refill_notes = actual.notes or ""
            used_actual = 1
        else:
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

        detected.append(
            {
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
        )

    report = {
        "apply": apply,
        "ons_months_loaded": len(ons),
        "actual_refills": len(actuals),
        "first_reliable_sensor": (
            {"date": first_reliable[0].strftime("%Y-%m-%d %H:%M:%S"),
             "ppl": first_reliable[1]}
            if first_reliable
            else None
        ),
        "existing_period_count": len(existing_payloads),
        "spurious_period_count": len(spurious),
        "spurious_period_end_dates": [s["end_date"] for s in spurious],
        "detected_period_count": len(detected),
        "ppl_source_breakdown": aggregate_sources,
        "before": existing_payloads,
        "after": detected,
    }

    if apply:
        async with sf() as session:
            # Wipe spurious + the detected-period rows we're rebuilding.
            await session.execute(
                delete(RefillPeriod).where(
                    RefillPeriod.start_date == SPURIOUS_PERIOD_START,
                    RefillPeriod.end_date.like("%-01 06:18:02"),
                )
            )
            for d in detected:
                existing = (
                    await session.execute(
                        select(RefillPeriod).where(
                            RefillPeriod.start_date == d["start_date"],
                            RefillPeriod.end_date == d["end_date"],
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(RefillPeriod(**d))
                else:
                    for k, v in d.items():
                        setattr(existing, k, v)
            await session.commit()

    return report
