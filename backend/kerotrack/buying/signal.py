"""Buy signal state machine for reorder decision making (pure, standard library only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


ALERT_STATES = frozenset({"buy_now", "deadline", "overdue"})


@dataclass(frozen=True, slots=True)
class SignalInputs:
    """Inputs to the buy signal state machine."""

    today: date
    headroom_l: float
    min_order_l: float
    order_by: date | None
    warn_days: int
    trigger_ppl: float
    # All in pence per litre (VAT, delivery and fees included), the same
    # basis as the trigger.
    best_ppl: float | None
    has_index: bool


def compute_state(inp: SignalInputs) -> str:
    """Compute the current buy signal state based on inputs.

    Priority order:
    1. no_room (headroom < min order)
    2. overdue (order_by and today > order_by)
    3. deadline (order_by and (order_by - today).days <= warn_days)
    4. buy_now (trigger > 0 and best not None and best <= trigger)
    5. wait (best not None or has_index)
    6. unknown (else)
    """
    # 1. no_room: headroom < min order
    if inp.headroom_l < inp.min_order_l:
        return "no_room"

    # 2. overdue: order_by and today > order_by
    if inp.order_by is not None and inp.today > inp.order_by:
        return "overdue"

    # 3. deadline: order_by and (order_by - today).days <= warn_days
    if inp.order_by is not None:
        days_until = (inp.order_by - inp.today).days
        if days_until <= inp.warn_days:
            return "deadline"

    # 4. buy_now: trigger > 0 and best not None and best <= trigger
    if (
        inp.trigger_ppl > 0
        and inp.best_ppl is not None
        and inp.best_ppl <= inp.trigger_ppl
    ):
        return "buy_now"

    # 5. wait: best not None or has_index
    if inp.best_ppl is not None or inp.has_index:
        return "wait"

    # 6. unknown (else)
    return "unknown"


def should_alert(previous: str | None, current: str) -> bool:
    """Determine if we should alert on a state transition.

    Alert only when transitioning into an alert state.
    """
    return current in ALERT_STATES and current != previous
