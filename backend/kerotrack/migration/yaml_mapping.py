"""Authoritative v1 YAML → v2 settings mapping (spec §9.3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Each entry is (yaml_path, v2_setting_key) where yaml_path is a dotted
# accessor into the loaded YAML dict. None for v2_setting_key means "ignored".


# Static keys (excluding the indexed mqtt.topics which are handled separately).
KEY_MAP: list[tuple[str, str | None]] = [
    ("database.path", None),
    ("database.cleanup_days", None),
    ("logging.directory", None),
    ("logging.level", None),
    ("logging.retention_days", None),
    ("web.secret_key", None),
    ("web.host", None),
    ("web.port", None),
    ("tank.capacity", "tank.capacity_l"),
    ("tank.length", "tank.length_cm"),
    ("tank.width", "tank.width_cm"),
    ("tank.height", "tank.height_cm"),
    ("tank.thermal_coefficient", "tank.thermal_coefficient"),
    ("boiler.model", "boiler.model"),
    ("boiler.burner", "boiler.burner"),
    ("boiler.nozzle", "boiler.nozzle"),
    ("boiler.fuel_rate", "boiler.fuel_rate_l_per_h"),
    ("boiler.input_kw", "boiler.input_kw"),
    ("boiler.output_kw", "boiler.output_kw"),
    ("boiler.fuel_pump_pressure", "boiler.fuel_pump_pressure"),
    ("boiler.efficiency", "boiler.efficiency_pct"),
    ("boiler.co2_percentage", "boiler.co2_percentage"),
    ("analysis.co2_per_liter", "analysis.co2_per_liter"),
    ("analysis.hdd_base_temperature", "analysis.hdd_base_temperature"),
    ("analysis.reference_temperature", "analysis.reference_temperature"),
    (
        "analysis.thermal_expansion_coefficient",
        "analysis.thermal_expansion_coefficient",
    ),
    ("analysis.oil_density_at_15c", "analysis.oil_density_at_15c"),
    ("analysis.viscosity_at_40c", "analysis.viscosity_at_40c"),
    ("analysis.tank_material_conductivity", "analysis.tank_material_conductivity"),
    ("analysis.tank_wall_thickness", "analysis.tank_wall_thickness_m"),
    ("analysis.oil_specific_heat", "analysis.oil_specific_heat"),
    ("analysis.ema_alpha", "analysis.ema_alpha"),
    ("energy.kwh_per_liter", "analysis.kwh_per_liter"),
    ("detection.refill_threshold", "detection.refill_threshold_l"),
    ("detection.leak_threshold", "detection.leak_threshold_l"),
    ("detection.max_daily_consumption_cold", "detection.max_daily_consumption_cold_l"),
    ("detection.max_daily_consumption_warm", "detection.max_daily_consumption_warm_l"),
    ("detection.warm_temperature_threshold", "detection.warm_temperature_threshold_c"),
    ("detection.leak_detection_period_days", "detection.leak_period_days"),
    ("detection.leak_rate_per_day", "detection.leak_rate_per_day_l"),
    ("mqtt.broker", "mqtt.broker"),
    ("mqtt.port", "mqtt.port"),
    ("mqtt.username", "mqtt.username"),
    ("mqtt.password", "mqtt.password"),
    ("mqtt.timeout_minutes", "mqtt.timeout_minutes"),
    ("mqtt.broadcast_interval_minutes", "mqtt.broadcast_interval_minutes"),
    ("notifications.apprise_urls", "notifications.apprise_urls"),
    ("oil_prices.url", "prices.homefuelsdirect_url"),
    ("alerts.low_level_threshold", "alerts.low_level_threshold_pct"),
    ("currency.symbol", "currency.symbol"),
]


def _walk(yaml: dict[str, Any], path: str) -> tuple[bool, Any]:
    cur: Any = yaml
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


@dataclass
class MappedKeys:
    settings: dict[str, Any]
    ignored: list[str]
    missing: list[str]


def map_yaml_to_settings(yaml: dict[str, Any]) -> MappedKeys:
    """Walk the v1 YAML dict and produce the v2 settings to write.

    Topics under `mqtt.topics` are projected by `name` → matching v2 key.
    """
    settings: dict[str, Any] = {}
    ignored: list[str] = []
    missing: list[str] = []

    for yaml_path, v2_key in KEY_MAP:
        present, value = _walk(yaml, yaml_path)
        if not present:
            missing.append(yaml_path)
            continue
        if v2_key is None:
            ignored.append(yaml_path)
            continue
        settings[v2_key] = value

    # mqtt.topics — list of dicts. v1 had two shapes:
    #   {name: "KTreadings", topicname: "oiltank/level"}   ← v1 publish targets
    #   {name: "lilygo/.../RTL_433toMQTT/...", qos: 0}     ← v1 subscribe source
    # In v2 `mqtt.topic_readings` is the SUBSCRIBE topic (spec §6.2). We pull
    # it from the RTL_433-shaped entry. The publish topic stays at
    # `oiltank/level` inside MqttPublisher's defaults.
    topics = yaml.get("mqtt", {}).get("topics", []) if isinstance(yaml, dict) else []
    name_to_v2 = {
        "KTanalytics": "mqtt.topic_analytics",
        "KTcostanalysis": "mqtt.topic_costanalysis",
    }
    for entry in topics:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "")
        topic_name = entry.get("topicname")
        v2_key = name_to_v2.get(name)
        if v2_key and topic_name:
            settings[v2_key] = topic_name
        # The subscribe topic in v1 has no `topicname` — its `name` IS the
        # MQTT topic, and contains "RTL_433toMQTT".
        if "RTL_433toMQTT" in name:
            settings["mqtt.topic_readings"] = name

    return MappedKeys(settings=settings, ignored=ignored, missing=missing)
