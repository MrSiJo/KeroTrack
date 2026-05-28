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

from sqlalchemy import asc, delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.clock import parse_local
from kerotrack.ingest.recalc import (
    NOISE_SUPPRESSED_SENTINEL,
    SANITY_BOUND_MAX_GAP_HOURS,
    _physical_change_bound_l,
    _raw_air_gap_litres,
)
from kerotrack.models.reading import Reading
from kerotrack.models.refill_period import RefillPeriod
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

    # `trusted` = the most recent row we believe represents reality. The
    # sanity bound compares every candidate against `trusted`, not the
    # immediately preceding row. This lets the cleanup mark chain noise
    # (the sensor stuck on a wrong reflection for N consecutive readings)
    # because each chain member's delta from the last trusted baseline is
    # huge even though its delta from the immediately previous (noisy)
    # row is tiny. `trusted` is only advanced when the candidate clears
    # the bound (or when the bound doesn't apply, e.g. multi-hour gaps).
    affected: list[dict[str, Any]] = []
    spurious_flag_dates: list[str] = []
    # Two-pointer walk:
    #   `prev`     = most recent reading regardless of noise. Used to
    #                detect outage gaps that disable the bound.
    #   `trusted`  = most recent reading we believe represents reality.
    #                The bound delta is measured against this.
    prev: Reading | None = None
    trusted: Reading | None = None
    for curr in rows:
        if trusted is None or prev is None:
            trusted = curr
            prev = curr
            continue
        if (
            curr.air_gap_cm is None
            or curr.temperature is None
            or trusted.air_gap_cm is None
        ):
            trusted = curr
            prev = curr
            continue
        trusted_dt = parse_local(trusted.date)
        prev_dt = parse_local(prev.date)
        curr_dt = parse_local(curr.date)
        if trusted_dt is None or prev_dt is None or curr_dt is None:
            trusted = curr
            prev = curr
            continue
        gap_from_prev_s = (curr_dt - prev_dt).total_seconds()
        interval_s = (curr_dt - trusted_dt).total_seconds()
        # Long real gap (outage) → reset baseline. Anything could have
        # happened during the gap, including a delivery.
        if not (0 < gap_from_prev_s <= SANITY_BOUND_MAX_GAP_HOURS * 3600):
            trusted = curr
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
        trusted_raw = _raw_air_gap_litres(
            air_gap_cm=float(trusted.air_gap_cm),
            height_cm=snap["tank_height_cm"],
            capacity_l=snap["tank_capacity_l"],
        )
        if abs(curr_raw - trusted_raw) > bound:
            affected.append(
                {
                    "date": curr.date,
                    "interval_minutes": round(interval_s / 60, 1),
                    "prev_air_gap_cm": float(trusted.air_gap_cm),
                    "curr_air_gap_cm": float(curr.air_gap_cm),
                    "delta_raw_l": round(curr_raw - trusted_raw, 1),
                    "bound_l": round(bound, 1),
                    "was_refill": curr.refill_detected == "y",
                    "was_leak": curr.leak_detected == "y",
                }
            )
            # Do NOT advance `trusted` — the chain stays compared
            # against the last good baseline. But advance `prev` so the
            # max-gap watchdog tracks the actual sample cadence.
            prev = curr
            continue
        # Within budget and matching trusted. If this row is currently
        # flagged 'y' it must be a spurious "return to truth" — the live
        # refill/leak detection fired against the bad immediately-prior
        # reading rather than the trusted baseline. Clear the flag (no
        # sentinel: the row's litres/air_gap are honest).
        if curr.refill_detected == "y" or curr.leak_detected == "y":
            spurious_flag_dates.append(curr.date)
        trusted = curr
        prev = curr

    if apply:
        affected_dates = {a["date"] for a in affected}
        spurious_dates = set(spurious_flag_dates)
        if affected_dates or spurious_dates:
            async with sf() as session:
                target_rows = (
                    (
                        await session.execute(
                            select(Reading).where(
                                Reading.date.in_(affected_dates | spurious_dates)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for row in target_rows:
                    row.refill_detected = "n"
                    row.leak_detected = "n"
                    if row.date in affected_dates:
                        row.raw_flags = _stamp_sentinel(row.raw_flags)
                await session.commit()

    # Clean up refill_periods rows whose end_date no longer corresponds
    # to a refill_detected='y' reading. Skip operator-curated rows
    # (non-empty invoice_ref or refill_notes) — those are real refills
    # the user has annotated and we don't want to surprise them.
    async with sf() as session:
        valid_anchors = set(
            (
                await session.execute(
                    select(Reading.date).where(Reading.refill_detected == "y")
                )
            )
            .scalars()
            .all()
        )
        candidate_periods = (
            (
                await session.execute(
                    select(RefillPeriod)
                )
            )
            .scalars()
            .all()
        )
        orphan_periods: list[dict[str, Any]] = []
        for p in candidate_periods:
            if p.end_date in valid_anchors:
                continue
            if (p.refill_invoice or "") or (p.refill_notes or ""):
                continue
            orphan_periods.append(
                {"start_date": p.start_date, "end_date": p.end_date}
            )
        if apply and orphan_periods:
            for op in orphan_periods:
                await session.execute(
                    delete(RefillPeriod).where(
                        RefillPeriod.start_date == op["start_date"],
                        RefillPeriod.end_date == op["end_date"],
                    )
                )
            await session.commit()

    return {
        "apply": apply,
        "reset_count": len(affected) + len(spurious_flag_dates),
        "noise_count": len(affected),
        "spurious_flag_count": len(spurious_flag_dates),
        "sample": affected[:50],
        "spurious_flag_sample": spurious_flag_dates[:50],
        "periods_deleted": len(orphan_periods),
        "periods_deleted_sample": orphan_periods[:50],
    }
