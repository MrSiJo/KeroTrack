"""Buy planner catalogue additions (spec: buy planner design)."""

from __future__ import annotations

import json

from kerotrack.settings.schema import SETTINGS_CATALOGUE


def test_buying_keys_present_with_defaults() -> None:
    c = SETTINGS_CATALOGUE
    assert c["buying.postcode"].is_secret is True
    assert c["buying.order_litres"].default == 500
    assert c["projection.reserve_l"].default == 100.0
    assert c["schedule.buying_cron"].default == "0 7,13 * * *"
    assert c["schedule.notifier_cron"].default == "0 8 * * *"
    assert c["schedule.analysis_cron"].default == "0 6 * * sun"
    assert c["schedule.cost_analysis_cron"].default == "0 7 * * sun"
    assert c["boiler.hw_burner_minutes_per_slot"].default == 33.0
    assert set(c["projection.scenarios"].default) == {
        "normal",
        "mild_then_cold",
        "cold",
    }


def test_new_group_membership_and_types() -> None:
    c = SETTINGS_CATALOGUE
    for key in ("buying.order_litres", "buying.providers", "buying.warn_days"):
        assert c[key].group == "buying"
    assert c["projection.active_scenario"].group == "projection"
    assert c["buying.postcode"].value_type == "secret"
    assert c["mqtt.topic_buying"].default == "oiltank/buying"
    slot = c["boiler.hw_burner_minutes_per_slot"]
    assert (slot.min_value, slot.max_value, slot.step) == (0.0, 60.0, 0.5)


def test_json_defaults_round_trip() -> None:
    for key in ("boiler.hw_schedule", "buying.providers", "projection.scenarios"):
        default = SETTINGS_CATALOGUE[key].default
        assert json.loads(json.dumps(default)) == default
    assert len(SETTINGS_CATALOGUE["boiler.hw_schedule"].default) == 2
