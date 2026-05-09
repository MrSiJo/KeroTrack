"""Canonical setting catalogue.

Every runtime-tunable value lives here. Keys not in this catalogue cannot be
written via the API (the catalogue is closed). Each entry carries the type used
for serialisation and form rendering, the group used for UI accordions, the
default used by the idempotent seed, and a flag for secrets so they can be
redacted on read and in the audit log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ValueType = Literal["string", "int", "float", "bool", "cron", "json", "secret"]
GroupName = Literal[
    "tank",
    "boiler",
    "mqtt",
    "analysis",
    "detection",
    "prices",
    "notifications",
    "schedule",
    "web",
    "alerts",
    "currency",
]


@dataclass(frozen=True, slots=True)
class SettingDef:
    """Catalogue entry for a single setting."""

    key: str
    value_type: ValueType
    group: GroupName
    label: str
    default: Any
    description: str = ""
    is_secret: bool = False
    requires_restart: bool = False
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None


def _entries() -> list[SettingDef]:
    e: list[SettingDef] = []

    # tank ---------------------------------------------------------------
    e += [
        SettingDef("tank.capacity_l", "float", "tank", "Tank capacity (L)", 1225.0),
        SettingDef("tank.length_cm", "float", "tank", "Tank length (cm)", 178.5),
        SettingDef("tank.width_cm", "float", "tank", "Tank width (cm)", 75.0),
        SettingDef("tank.height_cm", "float", "tank", "Tank height (cm)", 137.0),
        SettingDef(
            "tank.thermal_coefficient",
            "float",
            "tank",
            "Thermal coefficient",
            0.0007,
        ),
    ]

    # boiler -------------------------------------------------------------
    e += [
        SettingDef("boiler.model", "string", "boiler", "Boiler model", ""),
        SettingDef("boiler.burner", "string", "boiler", "Burner", ""),
        SettingDef("boiler.nozzle", "float", "boiler", "Nozzle (gph)", 0.60),
        SettingDef(
            "boiler.fuel_rate_l_per_h",
            "float",
            "boiler",
            "Fuel rate (L/h)",
            2.33,
        ),
        SettingDef("boiler.input_kw", "float", "boiler", "Input (kW)", 22.1),
        SettingDef("boiler.output_kw", "float", "boiler", "Output (kW)", 21.5),
        SettingDef(
            "boiler.fuel_pump_pressure",
            "int",
            "boiler",
            "Fuel pump pressure (psi)",
            140,
        ),
        SettingDef("boiler.efficiency_pct", "float", "boiler", "Efficiency %", 99.0),
        SettingDef(
            "boiler.co2_percentage", "float", "boiler", "Flue CO2 %", 11.8
        ),
    ]

    # analysis -----------------------------------------------------------
    e += [
        SettingDef(
            "analysis.co2_per_liter",
            "float",
            "analysis",
            "CO2 per litre (kg)",
            2.54,
        ),
        SettingDef(
            "analysis.hdd_base_temperature",
            "float",
            "analysis",
            "HDD base temperature (°C)",
            15.5,
        ),
        SettingDef(
            "analysis.reference_temperature",
            "float",
            "analysis",
            "Reference temperature (°C)",
            15.0,
        ),
        SettingDef(
            "analysis.thermal_expansion_coefficient",
            "float",
            "analysis",
            "Thermal expansion coefficient",
            0.0008,
        ),
        SettingDef(
            "analysis.oil_density_at_15c",
            "float",
            "analysis",
            "Oil density at 15°C (kg/m³)",
            800.0,
        ),
        SettingDef(
            "analysis.viscosity_at_40c",
            "float",
            "analysis",
            "Viscosity at 40°C",
            1.5,
        ),
        SettingDef(
            "analysis.tank_material_conductivity",
            "float",
            "analysis",
            "Tank material conductivity",
            0.4,
        ),
        SettingDef(
            "analysis.tank_wall_thickness_m",
            "float",
            "analysis",
            "Tank wall thickness (m)",
            0.005,
        ),
        SettingDef(
            "analysis.oil_specific_heat",
            "float",
            "analysis",
            "Oil specific heat",
            2000.0,
        ),
        SettingDef(
            "analysis.ema_alpha",
            "float",
            "analysis",
            "EMA smoothing alpha",
            0.2,
            min_value=0.0,
            max_value=1.0,
        ),
        SettingDef(
            "analysis.kwh_per_liter",
            "float",
            "analysis",
            "kWh per litre",
            10.35,
        ),
    ]

    # detection ----------------------------------------------------------
    e += [
        SettingDef(
            "detection.refill_threshold_l",
            "float",
            "detection",
            "Refill threshold (L)",
            100.0,
        ),
        SettingDef(
            "detection.leak_threshold_l",
            "float",
            "detection",
            "Leak threshold (L)",
            100.0,
        ),
        SettingDef(
            "detection.max_daily_consumption_cold_l",
            "float",
            "detection",
            "Max daily consumption — cold day (L)",
            55.0,
        ),
        SettingDef(
            "detection.max_daily_consumption_warm_l",
            "float",
            "detection",
            "Max daily consumption — warm day (L)",
            30.0,
        ),
        SettingDef(
            "detection.warm_temperature_threshold_c",
            "float",
            "detection",
            "Warm temperature threshold (°C)",
            16.0,
        ),
        SettingDef(
            "detection.leak_period_days",
            "int",
            "detection",
            "Leak detection window (days)",
            3,
        ),
        SettingDef(
            "detection.leak_rate_per_day_l",
            "float",
            "detection",
            "Leak rate (L/day)",
            10.0,
        ),
    ]

    # mqtt ---------------------------------------------------------------
    e += [
        SettingDef("mqtt.broker", "string", "mqtt", "MQTT broker host", "localhost"),
        SettingDef("mqtt.port", "int", "mqtt", "MQTT broker port", 1883),
        SettingDef("mqtt.username", "string", "mqtt", "MQTT username", ""),
        SettingDef(
            "mqtt.password",
            "secret",
            "mqtt",
            "MQTT password",
            "",
            is_secret=True,
        ),
        SettingDef(
            "mqtt.topic_readings",
            "string",
            "mqtt",
            "Readings topic (subscribe)",
            "lilygo/+/RTL_433toMQTT/Oil-SonicAdv/+",
        ),
        SettingDef(
            "mqtt.topic_readings_publish",
            "string",
            "mqtt",
            "Level topic (publish)",
            "oiltank/level",
        ),
        SettingDef(
            "mqtt.topic_analytics",
            "string",
            "mqtt",
            "Analysis topic (publish)",
            "oiltank/analysis",
        ),
        SettingDef(
            "mqtt.topic_costanalysis",
            "string",
            "mqtt",
            "Cost analysis topic (publish)",
            "oiltank/cost_analysis",
        ),
        SettingDef(
            "mqtt.timeout_minutes",
            "int",
            "mqtt",
            "Idle reconnect window (min)",
            35,
        ),
        SettingDef(
            "mqtt.broadcast_interval_minutes",
            "int",
            "mqtt",
            "Broadcast interval (min)",
            30,
        ),
    ]

    # prices -------------------------------------------------------------
    e += [
        SettingDef(
            "prices.boilerjuice_url",
            "string",
            "prices",
            "BoilerJuice URL",
            "https://www.boilerjuice.com/heating-oil-prices-england/",
        ),
        SettingDef(
            "prices.yournrg_url",
            "string",
            "prices",
            "YourNRG URL",
            "https://yournrg.co.uk/domestic/heating-oil-prices",
        ),
        SettingDef(
            "prices.cache_ttl_seconds",
            "int",
            "prices",
            "Price cache TTL (seconds)",
            86400,
        ),
    ]

    # notifications ------------------------------------------------------
    e += [
        SettingDef(
            "notifications.apprise_urls",
            "json",
            "notifications",
            "Apprise URLs",
            [],
        ),
        SettingDef(
            "notifications.weekly_enabled",
            "bool",
            "notifications",
            "Weekly summary enabled",
            True,
        ),
        SettingDef(
            "notifications.monthly_enabled",
            "bool",
            "notifications",
            "Monthly summary enabled",
            True,
        ),
    ]

    # schedule -----------------------------------------------------------
    e += [
        # Sunday morning cadence: analysis 06:00 → cost analysis 07:00 →
        # notifier 08:00. Notifier uses its internal weekly + first-Sunday
        # predicate for the body so a Sunday-only cron is fine.
        SettingDef(
            "schedule.analysis_cron",
            "cron",
            "schedule",
            "Analysis cron",
            "0 6 * * 0",
        ),
        SettingDef(
            "schedule.cost_analysis_cron",
            "cron",
            "schedule",
            "Cost analysis cron",
            "0 7 * * 0",
        ),
        SettingDef(
            "schedule.notifier_cron",
            "cron",
            "schedule",
            "Notifier cron",
            "0 8 * * 0",
        ),
    ]

    # alerts -------------------------------------------------------------
    e += [
        SettingDef(
            "alerts.low_level_threshold_pct",
            "float",
            "alerts",
            "Low-level alert threshold (%)",
            20.0,
            min_value=0.0,
            max_value=100.0,
        ),
    ]

    # currency -----------------------------------------------------------
    e += [
        SettingDef("currency.symbol", "string", "currency", "Currency symbol", "£"),
    ]

    # web ----------------------------------------------------------------
    e += [
        SettingDef(
            "web.theme_default",
            "string",
            "web",
            "Default theme",
            "system",
        ),
        SettingDef("web.title", "string", "web", "Page title", "KeroTrack"),
    ]

    return e


SETTINGS_CATALOGUE: dict[str, SettingDef] = {entry.key: entry for entry in _entries()}


def get_setting_def(key: str) -> SettingDef:
    """Return the catalogue entry for `key`, raising `KeyError` if unknown."""
    if key not in SETTINGS_CATALOGUE:
        raise KeyError(f"unknown_setting: {key}")
    return SETTINGS_CATALOGUE[key]


def all_keys() -> list[str]:
    return list(SETTINGS_CATALOGUE.keys())


def keys_in_group(group: GroupName) -> list[str]:
    return [k for k, v in SETTINGS_CATALOGUE.items() if v.group == group]
