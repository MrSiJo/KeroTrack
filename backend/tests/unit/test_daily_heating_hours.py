"""Daily heating hours for the usage trend (synthetic data)."""

from __future__ import annotations

from datetime import date

import pytest

from kerotrack.analysis.nest_model import daily_heating_hours


def test_daily_beats_monthly_beats_average() -> None:
    out = daily_heating_hours(
        date(2026, 1, 30),
        date(2026, 3, 2),
        daily={"2026-01-31": 5.0},
        monthly={"2026-01": 62.0, "2025-03": 31.0, "2024-03": 93.0, "2026-02": 28.0},
    )
    by_day = {i["date"]: i for i in out}
    assert by_day["2026-01-31"] == {"date": "2026-01-31", "hours": 5.0, "source": "daily"}
    assert by_day["2026-01-30"] == {"date": "2026-01-30", "hours": 2.0, "source": "monthly"}
    assert by_day["2026-02-10"] == {"date": "2026-02-10", "hours": 1.0, "source": "monthly"}
    # March 2026 has no report: mean of the March reports (62) over 31 days.
    assert by_day["2026-03-01"] == {"date": "2026-03-01", "hours": 2.0, "source": "average"}


def test_one_item_per_day_in_order() -> None:
    out = daily_heating_hours(date(2026, 1, 1), date(2026, 1, 10), daily={}, monthly={})
    assert [i["date"] for i in out] == [f"2026-01-{d:02d}" for d in range(1, 11)]
    assert all(i["hours"] == 0.0 and i["source"] == "average" for i in out)


def test_end_before_start_is_empty() -> None:
    assert daily_heating_hours(date(2026, 1, 2), date(2026, 1, 1), daily={}, monthly={}) == []


@pytest.mark.parametrize("bad", [-1.0, float("nan")])
def test_bad_daily_values_fall_through(bad: float) -> None:
    out = daily_heating_hours(
        date(2026, 1, 1), date(2026, 1, 1), daily={"2026-01-01": bad}, monthly={"2026-01": 31.0}
    )
    assert out == [{"date": "2026-01-01", "hours": 1.0, "source": "monthly"}]
