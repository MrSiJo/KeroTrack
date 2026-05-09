"""Catalogue tests — every key in spec §5.2 is present with the right type and default."""

from __future__ import annotations

import pytest

from kerotrack.settings.schema import SETTINGS_CATALOGUE, get_setting_def

# (key, value_type, group, default, is_secret) per spec §5.2.
EXPECTED_KEYS: list[tuple[str, str, str, object, bool]] = [
    ("tank.capacity_l", "float", "tank", 1225.0, False),
    ("tank.length_cm", "float", "tank", 178.5, False),
    ("tank.width_cm", "float", "tank", 75.0, False),
    ("tank.height_cm", "float", "tank", 137.0, False),
    ("tank.thermal_coefficient", "float", "tank", 0.0007, False),
    ("boiler.model", "string", "boiler", "", False),
    ("boiler.burner", "string", "boiler", "", False),
    ("boiler.nozzle", "float", "boiler", 0.60, False),
    ("boiler.fuel_rate_l_per_h", "float", "boiler", 2.33, False),
    ("boiler.input_kw", "float", "boiler", 22.1, False),
    ("boiler.output_kw", "float", "boiler", 21.5, False),
    ("boiler.fuel_pump_pressure", "int", "boiler", 140, False),
    ("boiler.efficiency_pct", "float", "boiler", 99.0, False),
    ("boiler.co2_percentage", "float", "boiler", 11.8, False),
    ("analysis.co2_per_liter", "float", "analysis", 2.54, False),
    ("analysis.hdd_base_temperature", "float", "analysis", 15.5, False),
    ("analysis.reference_temperature", "float", "analysis", 15.0, False),
    ("analysis.thermal_expansion_coefficient", "float", "analysis", 0.0008, False),
    ("analysis.oil_density_at_15c", "float", "analysis", 800.0, False),
    ("analysis.viscosity_at_40c", "float", "analysis", 1.5, False),
    ("analysis.tank_material_conductivity", "float", "analysis", 0.4, False),
    ("analysis.tank_wall_thickness_m", "float", "analysis", 0.005, False),
    ("analysis.oil_specific_heat", "float", "analysis", 2000.0, False),
    ("analysis.ema_alpha", "float", "analysis", 0.2, False),
    ("analysis.kwh_per_liter", "float", "analysis", 10.35, False),
    ("detection.refill_threshold_l", "float", "detection", 100.0, False),
    ("detection.leak_threshold_l", "float", "detection", 100.0, False),
    ("detection.max_daily_consumption_cold_l", "float", "detection", 55.0, False),
    ("detection.max_daily_consumption_warm_l", "float", "detection", 30.0, False),
    ("detection.warm_temperature_threshold_c", "float", "detection", 16.0, False),
    ("detection.leak_period_days", "int", "detection", 3, False),
    ("detection.leak_rate_per_day_l", "float", "detection", 10.0, False),
    ("mqtt.broker", "string", "mqtt", "localhost", False),
    ("mqtt.port", "int", "mqtt", 1883, False),
    ("mqtt.username", "string", "mqtt", "", False),
    ("mqtt.password", "secret", "mqtt", "", True),
    ("mqtt.topic_readings", "string", "mqtt",
     "lilygo/+/RTL_433toMQTT/Oil-SonicAdv/+", False),
    ("mqtt.topic_readings_publish", "string", "mqtt", "oiltank/level", False),
    ("mqtt.topic_analytics", "string", "mqtt", "oiltank/analysis", False),
    ("mqtt.topic_costanalysis", "string", "mqtt", "oiltank/cost_analysis", False),
    ("mqtt.timeout_minutes", "int", "mqtt", 35, False),
    ("mqtt.broadcast_interval_minutes", "int", "mqtt", 30, False),
    ("prices.boilerjuice_url", "string", "prices",
     "https://www.boilerjuice.com/heating-oil-prices-england/", False),
    ("prices.yournrg_url", "string", "prices",
     "https://yournrg.co.uk/domestic/heating-oil-prices", False),
    ("prices.cache_ttl_seconds", "int", "prices", 86400, False),
    ("notifications.apprise_urls", "json", "notifications", [], False),
    ("notifications.weekly_enabled", "bool", "notifications", True, False),
    ("notifications.monthly_enabled", "bool", "notifications", True, False),
    ("schedule.analysis_cron", "cron", "schedule", "0 6 * * 0", False),
    ("schedule.cost_analysis_cron", "cron", "schedule", "0 7 * * 0", False),
    ("schedule.notifier_cron", "cron", "schedule", "0 8 * * 0", False),
    ("alerts.low_level_threshold_pct", "float", "alerts", 20.0, False),
    ("currency.symbol", "string", "currency", "£", False),
    ("web.theme_default", "string", "web", "system", False),
    ("web.title", "string", "web", "KeroTrack", False),
]


@pytest.mark.parametrize("key,vt,group,default,is_secret", EXPECTED_KEYS)
def test_catalogue_has_expected_entry(
    key: str, vt: str, group: str, default: object, is_secret: bool
) -> None:
    assert key in SETTINGS_CATALOGUE
    definition = SETTINGS_CATALOGUE[key]
    assert definition.value_type == vt
    assert definition.group == group
    assert definition.default == default
    assert definition.is_secret is is_secret


def test_catalogue_size_matches_spec() -> None:
    # Spec §5.2 enumerates exactly these keys; guard against drift.
    assert len(SETTINGS_CATALOGUE) == len(EXPECTED_KEYS)


def test_get_setting_def_unknown_raises() -> None:
    with pytest.raises(KeyError):
        get_setting_def("nope.does.not.exist")


def test_secret_keys_are_flagged() -> None:
    secrets = {k for k, v in SETTINGS_CATALOGUE.items() if v.is_secret}
    assert secrets == {"mqtt.password"}
