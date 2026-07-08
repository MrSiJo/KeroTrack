"""Per-reading derived metrics.

Port of v1's `oil_recalc.py` — functions only, no module-level config load,
no logging side-effects on import. All tunables come from a `RecalcContext`
that the caller hydrates from `SettingsService`.

The output of `process()` is the v1-compatible `oiltank/level` dict (every
field per spec §3.1) — `cost_to_fill` is a string, percentages are floats,
`refill_detected` / `leak_detected` are `'y'` / `'n'`, etc. KeroDisplay's
parser must keep working byte-for-byte.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# Re-exported for existing importers (noise_reset, tests); the definition
# lives beside the trusted-readings query filter it drives (KERO-H3).
from kerotrack.models.reading import NOISE_SUPPRESSED_SENTINEL  # noqa: F401

logger = logging.getLogger(__name__)


# Watchman Sonic Advanced status byte (raw_flags). v1 stored the byte
# untouched but logged the decoded state — we do the same so non-Normal
# states show up in container logs without changing the wire format.
_STATUS_DECODE: dict[int, str] = {
    192: "Initial sync (20min fast reporting)",  # 0xC0
    128: "Post-sync calibration",  # 0x80
    144: "Transitional state",  # 0x90
    152: "Normal operation",  # 0x98
}


def decode_status(status: Any) -> str:
    """Return a human-readable label for a Watchman Sonic status byte."""
    try:
        key = int(status)
    except (TypeError, ValueError):
        return f"Unknown status: {status}"
    return _STATUS_DECODE.get(key, f"Unknown status: {key}")


@dataclass(frozen=True, slots=True)
class RecalcContext:
    """Settings snapshot used by `process()`.

    The lifespan task reads from `SettingsService` once and constructs this
    immutable view; the worker uses it for the duration of a reading. A new
    snapshot is produced on each incoming reading so settings changes are
    picked up without process restart.
    """

    tank_capacity_l: float
    tank_height_cm: float
    reference_temperature: float
    thermal_expansion_coefficient: float
    hdd_base_temperature: float
    refill_threshold_l: float
    leak_threshold_l: float
    leak_rate_per_day_l: float
    # Sanity-bound inputs — used to suppress refill/leak flags on
    # physically-impossible inter-reading deltas (Watchman Sonic multipath
    # misreads in warm/humid weather). The bound is:
    #     max_daily_l × interval_days × safety_multiplier
    # where max_daily_l switches on `warm_temperature_threshold_c`.
    max_daily_consumption_warm_l: float = 30.0
    max_daily_consumption_cold_l: float = 55.0
    warm_temperature_threshold_c: float = 16.0
    sanity_safety_multiplier: float = 2.0
    current_ppl: float | None = None


# ----------------------------------------------------------------- helpers


def calculate_hdd(temperature: float, base_temperature: float) -> float:
    return max(0.0, base_temperature - temperature)


def calculate_seasonal_efficiency(month: int) -> float:
    if month in {12, 1, 2}:
        return 0.95
    if month in {3, 4, 5, 9, 10, 11}:
        return 0.97
    return 0.99


def calculate_compensated_volume(
    air_gap_cm: float,
    temperature: float,
    *,
    height_cm: float,
    capacity_l: float,
    reference_temperature: float,
    thermal_expansion_coefficient: float,
) -> float:
    oil_height = height_cm - air_gap_cm
    raw_volume = (oil_height / height_cm) * capacity_l
    compensated = raw_volume / (
        1 + thermal_expansion_coefficient * (temperature - reference_temperature)
    )
    return max(0.0, min(compensated, capacity_l))


def calculate_bars(percentage: float) -> int:
    thresholds = [0, 15, 25, 35, 45, 55, 65, 75, 85, 95]
    for i, threshold in enumerate(thresholds):
        if percentage <= threshold:
            return max(1, i)
    return 10


# A refill must also move the physical oil surface: the volume jump alone
# can be thermal/noise artefact, so we require the air gap to shrink by more
# than this many cm too. ~5 cm ≈ 45 L on the 1225 L tank — well above the
# sensor's 1 cm quantisation jitter, well below any real delivery. Unlike
# the litre threshold (detection.refill_threshold_l) this is a property of
# the sensor's reporting, not the installation, so it stays a constant.
REFILL_MIN_AIR_GAP_DECREASE_CM = 5.0


def detect_refill(
    current_litres: float,
    previous_litres: float | None,
    current_air_gap: float,
    previous_air_gap: float | None,
    *,
    threshold_l: float,
) -> str:
    if previous_litres is None or previous_air_gap is None:
        return "n"
    volume_increase = current_litres - previous_litres
    air_gap_decrease = previous_air_gap - current_air_gap
    return (
        "y"
        if volume_increase >= threshold_l
        and air_gap_decrease > REFILL_MIN_AIR_GAP_DECREASE_CM
        else "n"
    )


# Inter-reading gaps longer than this disable the sanity bound. The
# Watchman Sonic broadcasts every ~30 min in normal operation; one
# missed broadcast lands the gap at ~60 min + broadcast-time jitter
# (real-world traces show 3601-3605 s). 1.25 h covers that window
# without admitting genuine multi-hour outage gaps where a refill could
# plausibly have happened.
SANITY_BOUND_MAX_GAP_HOURS = 1.25
# The Watchman Sonic Advanced reports air gap as an integer cm. A single
# real-consumption "tick" therefore looks like a 1 cm jump (~9 L on a
# 1225 L tank). We allow 2 cm of slack to absorb that quantisation plus a
# small amount of jitter — anything beyond is multipath. Expressed as the
# air-gap-derived raw volume; the consumption-budget gate above only
# tightens the bound when the gap is long enough for daily-rate to apply.
SANITY_BOUND_MIN_AIR_GAP_CM = 2.0


def _raw_air_gap_litres(
    *, air_gap_cm: float, height_cm: float, capacity_l: float
) -> float:
    """Convert an air-gap reading to litres without thermal compensation.

    The sanity-bound check needs to compare prev/current on the same
    basis, so we ignore the thermal correction here — otherwise a 10 °C
    swing between readings produces a 5 L "delta" at constant depth.
    """
    if height_cm <= 0:
        return 0.0
    oil_height = max(0.0, height_cm - air_gap_cm)
    return (oil_height / height_cm) * capacity_l


def _physical_change_bound_l(
    *,
    interval_seconds: float,
    current_temperature_c: float,
    max_warm_l_per_day: float,
    max_cold_l_per_day: float,
    warm_threshold_c: float,
    safety_multiplier: float,
    capacity_l: float,
    height_cm: float,
) -> float:
    """Maximum plausible raw |Δlitres| between two readings.

    Larger of two terms: (a) the daily-consumption budget pro-rated to
    the interval × safety_multiplier — meaningful at longer gaps; and
    (b) a sensor-quantisation floor (`SANITY_BOUND_MIN_AIR_GAP_CM`) so
    one cm of integer-rounded depth jitter at the normal 30-min cadence
    doesn't trip the bound.
    """
    max_per_day = (
        max_warm_l_per_day
        if current_temperature_c >= warm_threshold_c
        else max_cold_l_per_day
    )
    interval_days = max(interval_seconds, 0.0) / 86400.0
    budget = max_per_day * interval_days * safety_multiplier
    quantum_floor = (
        (capacity_l / height_cm) * SANITY_BOUND_MIN_AIR_GAP_CM
        if height_cm > 0
        else 0.0
    )
    return max(budget, quantum_floor)


def detect_leak(
    current_litres: float,
    previous_litres: float | None,
    current_date: datetime,
    previous_date: datetime | None,
    *,
    threshold_l: float,
    leak_rate_per_day_l: float,
) -> str:
    if previous_litres is None or previous_date is None:
        return "n"
    delta = current_date - previous_date
    if delta > timedelta(days=1):
        return "n"
    expected_loss = leak_rate_per_day_l * delta.total_seconds() / 86400.0
    actual_loss = previous_litres - current_litres
    return "y" if actual_loss > expected_loss and actual_loss >= threshold_l else "n"


# -------------------------------------------------------------- core process


@dataclass(frozen=True, slots=True)
class PreviousReading:
    date: datetime
    litres_remaining: float
    air_gap_cm: float
    # The most recent reading in the DB, regardless of whether it was
    # noise-suppressed. The sanity-bound watchdog uses THIS to decide
    # whether the sensor was alive: after a chain of suppressed rows,
    # `date` (the trusted baseline) can be hours older than
    # `most_recent_date` while the sensor itself was broadcasting every
    # 30 min. Defaults to `date` for the cold-start / first-reading case.
    most_recent_date: datetime | None = None


def process(
    reading: dict[str, Any],
    ctx: RecalcContext,
    *,
    previous: PreviousReading | None = None,
) -> dict[str, Any]:
    """Transform a Watchman Sonic Advanced JSON payload into an `oiltank/level` dict.

    `reading` is the raw RTL_433 payload — keys: `time`, `id`, `temperature_C`,
    `depth_cm`, `model`, optional `status`, `rssi`. `previous` is the most
    recent stored reading (or None on a cold start).

    Output is byte-compatible with v1: `cost_to_fill` is a quoted string,
    `refill_detected`/`leak_detected` are `"y"`/`"n"`, every numeric is rounded
    the same way.
    """
    current_date = datetime.strptime(reading["time"], "%Y-%m-%d %H:%M:%S")
    current_air_gap = float(reading["depth_cm"])
    current_temp = float(reading["temperature_C"])

    if "status" in reading and reading["status"] is not None:
        try:
            status_byte = int(reading["status"])
        except (TypeError, ValueError):
            status_byte = None
        if status_byte is not None and status_byte != 152:
            logger.info(
                "Sensor status: %s (%s)", decode_status(status_byte), status_byte
            )

    current_litres = calculate_compensated_volume(
        current_air_gap,
        current_temp,
        height_cm=ctx.tank_height_cm,
        capacity_l=ctx.tank_capacity_l,
        reference_temperature=ctx.reference_temperature,
        thermal_expansion_coefficient=ctx.thermal_expansion_coefficient,
    )

    if previous is not None:
        litres_used = max(0.0, previous.litres_remaining - current_litres)
        prev_litres = previous.litres_remaining
        prev_air_gap = previous.air_gap_cm
        prev_date = previous.date
    else:
        litres_used = 0.0
        prev_litres = None
        prev_air_gap = None
        prev_date = None

    percentage = (current_litres / ctx.tank_capacity_l) * 100.0 if ctx.tank_capacity_l else 0.0
    bars_remaining = calculate_bars(percentage)
    ppl = ctx.current_ppl

    cost_used = (
        f"{(litres_used * ppl / 100):.2f}" if ppl else "0.00"
    )
    cost_to_fill = (
        f"{((ctx.tank_capacity_l - current_litres) * ppl / 100):.2f}"
        if ppl
        else "0.00"
    )

    refill_flag = detect_refill(
        current_litres,
        prev_litres,
        current_air_gap,
        prev_air_gap,
        threshold_l=ctx.refill_threshold_l,
    )
    leak_flag = detect_leak(
        current_litres,
        prev_litres,
        current_date,
        prev_date,
        threshold_l=ctx.leak_threshold_l,
        leak_rate_per_day_l=ctx.leak_rate_per_day_l,
    )
    raw_flags: Any = reading.get("status")

    # Sanity bound: Watchman Sonic Advanced locks onto secondary reflections
    # in hot weather, producing 30-min depth jumps far beyond any plausible
    # consumption rate. The raw depth is recorded as-sensed, but the derived
    # refill/leak flags are suppressed so downstream analysis (refill anchor,
    # weekly digest) isn't poisoned. A sentinel is appended to raw_flags so
    # the row is recognisable in audits and in the UI.
    if prev_air_gap is not None and prev_date is not None:
        interval_s = (current_date - prev_date).total_seconds()
        # Cadence watchdog: use the most recent reading in DB (trusted
        # OR noise-suppressed) for the gap check, not the trusted date.
        # A chain of suppressed readings still proves the sensor was
        # alive, so the bound should keep applying.
        watchdog_date = (
            previous.most_recent_date if previous is not None and previous.most_recent_date is not None
            else prev_date
        )
        watchdog_gap_s = (current_date - watchdog_date).total_seconds()
        if interval_s > 0:
            bound = _physical_change_bound_l(
                interval_seconds=interval_s,
                current_temperature_c=current_temp,
                max_warm_l_per_day=ctx.max_daily_consumption_warm_l,
                max_cold_l_per_day=ctx.max_daily_consumption_cold_l,
                warm_threshold_c=ctx.warm_temperature_threshold_c,
                safety_multiplier=ctx.sanity_safety_multiplier,
                capacity_l=ctx.tank_capacity_l,
                height_cm=ctx.tank_height_cm,
            )
            curr_raw_l = _raw_air_gap_litres(
                air_gap_cm=current_air_gap,
                height_cm=ctx.tank_height_cm,
                capacity_l=ctx.tank_capacity_l,
            )
            prev_raw_l = _raw_air_gap_litres(
                air_gap_cm=prev_air_gap,
                height_cm=ctx.tank_height_cm,
                capacity_l=ctx.tank_capacity_l,
            )
            # Direction-aware gate. A level DROP (apparent leak/consumption)
            # can never legitimately beat the consumption budget at ANY gap
            # length — you cannot burn oil faster than max_daily_l — so leak
            # suppression stays armed even after the sensor misses several
            # broadcasts (the May 29 2026 phantom: a 1.5 h gap, two missed
            # broadcasts, an 80 → 93 cm multipath jump read as a 116 L loss).
            # A level RISE, by contrast, CAN be a genuine fast delivery after
            # a real outage, so refill suppression releases once the cadence
            # watchdog gap exceeds SANITY_BOUND_MAX_GAP_HOURS — otherwise we'd
            # eat a real refill that landed while the sensor was offline.
            is_drop = curr_raw_l < prev_raw_l
            within_gap = 0 < watchdog_gap_s <= SANITY_BOUND_MAX_GAP_HOURS * 3600
            if abs(curr_raw_l - prev_raw_l) > bound and (is_drop or within_gap):
                refill_flag = "n"
                leak_flag = "n"
                raw_flags = (
                    f"{raw_flags}:{NOISE_SUPPRESSED_SENTINEL}"
                    if raw_flags is not None
                    else NOISE_SUPPRESSED_SENTINEL
                )

    return {
        "date": current_date.strftime("%Y-%m-%d %H:%M:%S"),
        "id": reading["id"],
        "temperature": current_temp,
        "litres_remaining": round(current_litres, 1),
        "litres_used_since_last": round(litres_used, 1),
        "percentage_remaining": round(percentage, 1),
        "oil_depth_cm": round(ctx.tank_height_cm - current_air_gap, 1),
        "air_gap_cm": round(current_air_gap, 1),
        "current_ppl": ppl if ppl is not None else 0.0,
        "cost_used": cost_used,
        "cost_to_fill": cost_to_fill,
        "heating_degree_days": calculate_hdd(current_temp, ctx.hdd_base_temperature),
        "seasonal_efficiency": calculate_seasonal_efficiency(current_date.month),
        "refill_detected": refill_flag,
        "leak_detected": leak_flag,
        "raw_flags": raw_flags,
        "litres_to_order": round(ctx.tank_capacity_l - current_litres, 1),
        "bars_remaining": bars_remaining,
    }


async def context_from_settings(
    settings_service,
    *,
    current_ppl: float | None = None,
) -> RecalcContext:
    """Build a `RecalcContext` from the live settings service.

    `current_ppl` is plumbed in from the price scraper; without it, cost_used
    and cost_to_fill collapse to "0.00" exactly like the bug seen in the
    first live reading.
    """
    g = settings_service.get
    return RecalcContext(
        tank_capacity_l=float(await g("tank.capacity_l")),
        tank_height_cm=float(await g("tank.height_cm")),
        reference_temperature=float(await g("analysis.reference_temperature")),
        thermal_expansion_coefficient=float(
            await g("analysis.thermal_expansion_coefficient")
        ),
        hdd_base_temperature=float(await g("analysis.hdd_base_temperature")),
        refill_threshold_l=float(await g("detection.refill_threshold_l")),
        leak_threshold_l=float(await g("detection.leak_threshold_l")),
        leak_rate_per_day_l=float(await g("detection.leak_rate_per_day_l")),
        max_daily_consumption_warm_l=float(
            await g("detection.max_daily_consumption_warm_l")
        ),
        max_daily_consumption_cold_l=float(
            await g("detection.max_daily_consumption_cold_l")
        ),
        warm_temperature_threshold_c=float(
            await g("detection.warm_temperature_threshold_c")
        ),
        sanity_safety_multiplier=float(
            await g("detection.sanity_safety_multiplier")
        ),
        current_ppl=current_ppl,
    )
