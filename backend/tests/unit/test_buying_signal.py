"""Buy signal state machine for reorder decision making."""

from __future__ import annotations

from datetime import date

import pytest

from kerotrack.buying.signal import ALERT_STATES, SignalInputs, compute_state, should_alert


T = date(2026, 10, 5)


def _i(**kw):
    """Build a SignalInputs with defaults."""
    base = dict(
        today=T,
        headroom_l=760,
        min_order_l=500,
        order_by=date(2027, 1, 20),
        warn_days=14,
        trigger_ppl=95.0,
        best_ppl_effective=110.0,
        has_index=True,
    )
    base.update(kw)
    return SignalInputs(**base)


@pytest.mark.parametrize(
    "kw,state",
    [
        (dict(headroom_l=400), "no_room"),
        (dict(order_by=date(2026, 10, 1)), "overdue"),
        (dict(order_by=date(2026, 10, 19)), "deadline"),
        (dict(best_ppl_effective=94.0), "buy_now"),
        (dict(trigger_ppl=0.0, best_ppl_effective=50.0), "wait"),
        (dict(), "wait"),
        (dict(best_ppl_effective=None, has_index=False), "unknown"),
        (dict(headroom_l=400, order_by=date(2026, 10, 1)), "no_room"),
        (dict(order_by=None, best_ppl_effective=None, has_index=True), "wait"),
    ],
)
def test_states(kw, state):
    """Test state transitions."""
    assert compute_state(_i(**kw)) == state


def test_alert_only_on_transition_into_alert_states():
    """Test should_alert logic."""
    assert should_alert("wait", "buy_now")
    assert not should_alert("buy_now", "buy_now")
    assert not should_alert("buy_now", "wait")
    assert should_alert(None, "deadline")
