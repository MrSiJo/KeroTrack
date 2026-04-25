"""v1 YAML → v2 settings mapping coverage."""

from __future__ import annotations

import yaml as yaml_lib

from kerotrack.migration.yaml_mapping import map_yaml_to_settings


SAMPLE = """
database:
  path: /opt/KeroTrack/data/KeroTrack_data.db
logging:
  directory: /opt/KeroTrack/logs
  level: INFO
web:
  secret_key: redacted
  host: 0.0.0.0
  port: 5000
notifications:
  apprise_urls:
    - gotify://host/token
analysis:
  co2_per_liter: 2.54
  hdd_base_temperature: 15.5
  reference_temperature: 15.0
  thermal_expansion_coefficient: 0.0008
  oil_density_at_15c: 800
  viscosity_at_40c: 1.5
  tank_material_conductivity: 0.4
  tank_wall_thickness: 0.005
  oil_specific_heat: 2000
  ema_alpha: 0.2
alerts:
  low_level_threshold: 20.0
currency:
  symbol: "£"
tank:
  capacity: 1225
  length: 178.5
  width: 75
  height: 137
  thermal_coefficient: 0.0007
boiler:
  model: WB
  burner: RDB 2.2
  nozzle: 0.60
  fuel_rate: 2.33
  co2_percentage: 11.8
  input_kw: 22.1
  output_kw: 21.5
  fuel_pump_pressure: 140
  efficiency: 99
detection:
  refill_threshold: 100
  leak_threshold: 100
  max_daily_consumption_cold: 55
  max_daily_consumption_warm: 30
  warm_temperature_threshold: 16
  leak_detection_period_days: 3
mqtt:
  broker: 172.16.0.32
  port: 1883
  username: oil
  password: oil
  timeout_minutes: 35
  broadcast_interval_minutes: 30
  topics:
    - name: KTreadings
      topicname: oiltank/level
    - name: KTanalytics
      topicname: oiltank/analysis
    - name: KTcostanalysis
      topicname: oiltank/cost_analysis
"""


def test_every_mapped_key_lands_in_settings() -> None:
    mapped = map_yaml_to_settings(yaml_lib.safe_load(SAMPLE))
    expected = {
        "tank.capacity_l": 1225,
        "tank.length_cm": 178.5,
        "boiler.model": "WB",
        "boiler.fuel_rate_l_per_h": 2.33,
        "mqtt.broker": "172.16.0.32",
        "mqtt.password": "oil",
        "mqtt.topic_readings": "oiltank/level",
        "mqtt.topic_analytics": "oiltank/analysis",
        "mqtt.topic_costanalysis": "oiltank/cost_analysis",
        "alerts.low_level_threshold_pct": 20.0,
        "currency.symbol": "£",
        "notifications.apprise_urls": ["gotify://host/token"],
    }
    for key, value in expected.items():
        assert mapped.settings.get(key) == value, (key, value)


def test_ignored_keys_are_listed() -> None:
    mapped = map_yaml_to_settings(yaml_lib.safe_load(SAMPLE))
    assert "database.path" in mapped.ignored
    assert "web.secret_key" in mapped.ignored
    assert "logging.level" in mapped.ignored


def test_missing_sections_tolerated() -> None:
    mapped = map_yaml_to_settings({"tank": {"capacity": 999}})
    assert mapped.settings.get("tank.capacity_l") == 999
    # Other paths missing → reported, not crashed.
    assert "boiler.model" in mapped.missing


def test_empty_yaml() -> None:
    mapped = map_yaml_to_settings({})
    assert mapped.settings == {}
    assert mapped.missing  # everything is missing
