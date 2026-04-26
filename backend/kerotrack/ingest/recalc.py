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
    tank_length_cm: float
    tank_width_cm: float
    tank_height_cm: float
    thermal_coefficient: float
    reference_temperature: float
    thermal_expansion_coefficient: float
    hdd_base_temperature: float
    refill_threshold_l: float
    leak_threshold_l: float
    leak_rate_per_day_l: float
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
    return "y" if volume_increase >= threshold_l and air_gap_decrease > 5 else "n"


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
        "refill_detected": detect_refill(
            current_litres,
            prev_litres,
            current_air_gap,
            prev_air_gap,
            threshold_l=ctx.refill_threshold_l,
        ),
        "leak_detected": detect_leak(
            current_litres,
            prev_litres,
            current_date,
            prev_date,
            threshold_l=ctx.leak_threshold_l,
            leak_rate_per_day_l=ctx.leak_rate_per_day_l,
        ),
        "raw_flags": reading.get("status"),
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
        tank_length_cm=float(await g("tank.length_cm")),
        tank_width_cm=float(await g("tank.width_cm")),
        tank_height_cm=float(await g("tank.height_cm")),
        thermal_coefficient=float(await g("tank.thermal_coefficient")),
        reference_temperature=float(await g("analysis.reference_temperature")),
        thermal_expansion_coefficient=float(
            await g("analysis.thermal_expansion_coefficient")
        ),
        hdd_base_temperature=float(await g("analysis.hdd_base_temperature")),
        refill_threshold_l=float(await g("detection.refill_threshold_l")),
        leak_threshold_l=float(await g("detection.leak_threshold_l")),
        leak_rate_per_day_l=float(await g("detection.leak_rate_per_day_l")),
        current_ppl=current_ppl,
    )
