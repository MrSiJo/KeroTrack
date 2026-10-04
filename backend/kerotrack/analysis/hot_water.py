"""Hot water draw from the owner's boiler schedule (spec A3).

The tank sensor reads in ~13 L steps, so it often cannot see hot water use.
The schedule says when the boiler heats water; the burner fires for
``burner_minutes`` of each 1 h slot at ``fuel_rate_l_per_h``.
"""

from __future__ import annotations

import math
import re

WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def validate_schedule(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("hw_schedule must be a list of slots")
    out: list[dict] = []
    for slot in raw:
        if not isinstance(slot, dict):
            raise ValueError("each slot must be an object")
        days = slot.get("days")
        if not isinstance(days, list) or not days or any(d not in WEEKDAYS for d in days):
            raise ValueError(f"bad days in slot {slot!r}")
        if len(set(days)) != len(days):
            raise ValueError(f"duplicate days in slot {slot!r}")
        start = str(slot.get("start", "00:00"))
        if not _HHMM.match(start):
            raise ValueError(f"bad start time {start!r}")
        hours = slot.get("hours", 1.0)
        if (
            isinstance(hours, bool)
            or not isinstance(hours, (int, float))
            or not math.isfinite(hours)
            or hours <= 0
            or hours > 24
        ):
            raise ValueError(f"bad hours {hours!r}")
        out.append({"days": list(days), "start": start, "hours": float(hours)})
    return out


def slots_per_weekday(schedule: list[dict]) -> dict[int, float]:
    per = {i: 0.0 for i in range(7)}
    for slot in validate_schedule(schedule):
        for d in slot["days"]:
            per[WEEKDAYS.index(d)] += slot["hours"]
    return per


def slots_per_week(schedule: list[dict]) -> float:
    return sum(slots_per_weekday(schedule).values())


def hw_litres_for_weekday(
    schedule: list[dict], weekday: int, burner_minutes: float, fuel_rate_l_per_h: float
) -> float:
    hours = slots_per_weekday(schedule)[weekday]
    return hours * (burner_minutes / 60.0) * fuel_rate_l_per_h


def hw_litres_per_day_avg(
    schedule: list[dict], burner_minutes: float, fuel_rate_l_per_h: float
) -> float:
    return slots_per_week(schedule) * (burner_minutes / 60.0) * fuel_rate_l_per_h / 7.0
