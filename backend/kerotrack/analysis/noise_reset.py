"""One-shot historical reset for refill/leak flags poisoned by Watchman
Sonic Advanced multipath misreads.

The live ingest (``ingest/recalc.py``) applies a sanity bound to suppress
implausibly large depth deltas at the normal 30-min reading cadence. This
module replays the same bound across every existing ``readings`` row so
historical rows that fired ``refill_detected='y'`` / ``leak_detected='y'``
on multipath spikes get cleared retroactively.

Dry-run by default. Pass ``apply=True`` to mutate. After applying, run
``kerotrack rebuild-costs --apply`` to regenerate ``refill_periods`` from
the corrected refill set.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.clock import parse_local
from kerotrack.ingest.recalc import (
    NOISE_SUPPRESSED_SENTINEL,
    SANITY_BOUND_MAX_GAP_HOURS,
    _physical_change_bound_l,
    _raw_air_gap_litres,
)
from kerotrack.models.reading import Reading
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)


async def _detection_snapshot(svc: SettingsService) -> dict[str, float]:
    g = svc.get
    return {
        "tank_capacity_l": float(await g("tank.capacity_l")),
        "tank_height_cm": float(await g("tank.height_cm")),
        "max_warm_l_per_day": float(
            await g("detection.max_daily_consumption_warm_l")
        ),
        "max_cold_l_per_day": float(
            await g("detection.max_daily_consumption_cold_l")
        ),
        "warm_threshold_c": float(
            await g("detection.warm_temperature_threshold_c")
        ),
        "safety_multiplier": float(
            await g("detection.sanity_safety_multiplier")
        ),
    }


def _stamp_sentinel(raw_flags: str | None) -> str:
    if raw_flags is None or raw_flags == "":
        return NOISE_SUPPRESSED_SENTINEL
    if NOISE_SUPPRESSED_SENTINEL in raw_flags:
        return raw_flags
    return f"{raw_flags}:{NOISE_SUPPRESSED_SENTINEL}"


async def reset_noise_flags(
    sf: async_sessionmaker,
    svc: SettingsService,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Reset spurious refill_detected / leak_detected flags on historical rows.

    Returns a report with the count and a sample of affected rows. Mutates
    only when ``apply=True``.
    """
    snap = await _detection_snapshot(svc)

    async with sf() as session:
        rows = (
            (
                await session.execute(
                    select(Reading).order_by(asc(Reading.date))
                )
            )
            .scalars()
            .all()
        )

    affected: list[dict[str, Any]] = []
    prev: Reading | None = None
    for curr in rows:
        if prev is None:
            prev = curr
            continue
        if curr.refill_detected != "y" and curr.leak_detected != "y":
            prev = curr
            continue
        prev_dt = parse_local(prev.date)
        curr_dt = parse_local(curr.date)
        if (
            prev_dt is None
            or curr_dt is None
            or prev.air_gap_cm is None
            or curr.air_gap_cm is None
            or curr.temperature is None
        ):
            prev = curr
            continue
        interval_s = (curr_dt - prev_dt).total_seconds()
        if not (0 < interval_s <= SANITY_BOUND_MAX_GAP_HOURS * 3600):
            prev = curr
            continue
        bound = _physical_change_bound_l(
            interval_seconds=interval_s,
            current_temperature_c=float(curr.temperature),
            max_warm_l_per_day=snap["max_warm_l_per_day"],
            max_cold_l_per_day=snap["max_cold_l_per_day"],
            warm_threshold_c=snap["warm_threshold_c"],
            safety_multiplier=snap["safety_multiplier"],
            capacity_l=snap["tank_capacity_l"],
            height_cm=snap["tank_height_cm"],
        )
        curr_raw = _raw_air_gap_litres(
            air_gap_cm=float(curr.air_gap_cm),
            height_cm=snap["tank_height_cm"],
            capacity_l=snap["tank_capacity_l"],
        )
        prev_raw = _raw_air_gap_litres(
            air_gap_cm=float(prev.air_gap_cm),
            height_cm=snap["tank_height_cm"],
            capacity_l=snap["tank_capacity_l"],
        )
        if abs(curr_raw - prev_raw) > bound:
            affected.append(
                {
                    "date": curr.date,
                    "interval_minutes": round(interval_s / 60, 1),
                    "prev_air_gap_cm": float(prev.air_gap_cm),
                    "curr_air_gap_cm": float(curr.air_gap_cm),
                    "delta_raw_l": round(curr_raw - prev_raw, 1),
                    "bound_l": round(bound, 1),
                    "was_refill": curr.refill_detected == "y",
                    "was_leak": curr.leak_detected == "y",
                }
            )
        prev = curr

    report: dict[str, Any] = {
        "apply": apply,
        "reset_count": len(affected),
        "sample": affected[:50],
    }

    if apply and affected:
        affected_dates = {a["date"] for a in affected}
        async with sf() as session:
            target_rows = (
                (
                    await session.execute(
                        select(Reading).where(Reading.date.in_(affected_dates))
                    )
                )
                .scalars()
                .all()
            )
            for row in target_rows:
                row.refill_detected = "n"
                row.leak_detected = "n"
                row.raw_flags = _stamp_sentinel(row.raw_flags)
            await session.commit()

    return report
