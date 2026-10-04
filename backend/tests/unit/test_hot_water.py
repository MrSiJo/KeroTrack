import pytest
from kerotrack.analysis.hot_water import (
    validate_schedule, slots_per_weekday, hw_litres_for_weekday,
    hw_litres_per_day_avg, slots_per_week,
)

DEFAULT = [
    {"days": ["mon","tue","wed","thu","fri","sat","sun"], "start": "03:00", "hours": 1.0},
    {"days": ["fri","sat","sun"], "start": "16:30", "hours": 1.0},
]

def test_default_reproduces_legacy_183():
    assert hw_litres_per_day_avg(DEFAULT, 33.0, 2.33) == pytest.approx(1.8307, abs=1e-3)

def test_weekday_split():
    per = slots_per_weekday(DEFAULT)
    assert per[0] == 1.0 and per[4] == 2.0 and per[6] == 2.0
    assert hw_litres_for_weekday(DEFAULT, 5, 15.0, 2.33) == pytest.approx(2 * 15 / 60 * 2.33)
    assert slots_per_week(DEFAULT) == 10.0

def test_validate_rejects_bad_day_and_hours():
    with pytest.raises(ValueError):
        validate_schedule([{"days": ["funday"], "start": "03:00", "hours": 1}])
    with pytest.raises(ValueError):
        validate_schedule([{"days": ["mon"], "start": "03:00", "hours": -1}])
    with pytest.raises(ValueError):
        validate_schedule("nope")

def test_empty_schedule_is_zero():
    assert hw_litres_per_day_avg([], 33.0, 2.33) == 0.0

@pytest.mark.parametrize("hours", [True, False, float("nan"), float("inf"), float("-inf")])
def test_validate_rejects_bool_and_non_finite_hours(hours):
    with pytest.raises(ValueError):
        validate_schedule([{"days": ["mon"], "start": "03:00", "hours": hours}])

def test_validate_rejects_duplicate_days_in_a_slot():
    with pytest.raises(ValueError):
        validate_schedule([{"days": ["mon", "mon"], "start": "03:00", "hours": 1.0}])

def test_validate_allows_same_day_across_slots():
    assert len(validate_schedule(DEFAULT)) == 2
