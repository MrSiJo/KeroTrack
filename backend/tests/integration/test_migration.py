"""End-to-end migration against the sanitised v1 fixture."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.migration.v1_to_v2 import migrate
from kerotrack.models.reading import Reading
from kerotrack.models.refill_period import RefillPeriod


pytestmark = pytest.mark.asyncio


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "v1_sample.db"
SAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "fixtures" / "v1_config.yaml"


@pytest.fixture(autouse=True, scope="module")
def _ensure_yaml_fixture() -> None:
    SAMPLE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    SAMPLE_CONFIG.write_text(
        """
database:
  path: /opt/KeroTrack/data/KeroTrack_data.db
logging:
  directory: /opt/KeroTrack/logs
  level: INFO
notifications:
  apprise_urls:
    - gotify://host/token
analysis:
  co2_per_liter: 2.54
  hdd_base_temperature: 15.5
  reference_temperature: 15.0
  thermal_expansion_coefficient: 0.0008
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
  fuel_rate: 2.33
  co2_percentage: 11.8
  input_kw: 22.1
  output_kw: 21.5
  fuel_pump_pressure: 140
  efficiency: 99
detection:
  refill_threshold: 100
  leak_threshold: 100
mqtt:
  broker: localhost
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
"""
    )


def _src_count(table: str) -> int:
    src = sqlite3.connect(f"file:{FIXTURE.as_posix()}?mode=ro", uri=True)
    try:
        cur = src.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]
    finally:
        src.close()


async def test_dry_run_leaves_destination_empty(
    sf: async_sessionmaker, seeded_settings
) -> None:
    report = await migrate(
        src_db=FIXTURE,
        src_config=SAMPLE_CONFIG,
        sf=sf,
        settings_service=seeded_settings,
        dry_run=True,
    )
    async with sf() as session:
        count = (await session.execute(select(Reading.date))).all()
    assert count == []
    # report counts the source rows.
    assert report.rows_per_table["readings"]["source"] == _src_count("readings")
    assert report.rows_per_table["readings"]["copied"] == _src_count("readings")


async def test_wet_run_copies_rows_and_writes_settings(
    sf: async_sessionmaker, seeded_settings
) -> None:
    report = await migrate(
        src_db=FIXTURE,
        src_config=SAMPLE_CONFIG,
        sf=sf,
        settings_service=seeded_settings,
    )
    expected = _src_count("readings")
    assert report.rows_per_table["readings"]["copied"] == expected
    async with sf() as session:
        actual = len(
            (await session.execute(select(Reading.date))).all()
        )
    assert actual == expected
    # Settings come across.
    assert "tank.capacity_l" in report.settings_written
    assert await seeded_settings.get("tank.capacity_l") == 1225.0
    assert await seeded_settings.get("mqtt.broker") == "localhost"
    # v1 had nullable PKs in analysis_results — those rows are reported as skipped.
    if report.rows_per_table["analysis_results"]["skipped"]:
        assert any(
            sr["table"] == "analysis_results"
            for sr in report.skipped_rows
        )


async def test_idempotency_refuses_without_force(
    sf: async_sessionmaker, seeded_settings, tmp_path: Path
) -> None:
    await migrate(
        src_db=FIXTURE,
        src_config=SAMPLE_CONFIG,
        sf=sf,
        settings_service=seeded_settings,
    )
    with pytest.raises(RuntimeError, match="non-empty"):
        await migrate(
            src_db=FIXTURE,
            src_config=SAMPLE_CONFIG,
            sf=sf,
            settings_service=seeded_settings,
        )


async def test_force_re_runs_cleanly(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await migrate(
        src_db=FIXTURE, src_config=SAMPLE_CONFIG,
        sf=sf, settings_service=seeded_settings,
    )
    # Second run with --force is allowed; rows duplicate (composite PK still
    # matches but not raises). With composite PKs that already match, SQLite
    # raises IntegrityError → captured in report.skipped_rows.
    second = await migrate(
        src_db=FIXTURE, src_config=SAMPLE_CONFIG,
        sf=sf, settings_service=seeded_settings,
        force=True,
    )
    assert "readings" in second.rows_per_table


async def test_tolerates_missing_optional_tables(
    tmp_path: Path, sf: async_sessionmaker, seeded_settings
) -> None:
    minimal_db = tmp_path / "minimal.db"
    src = sqlite3.connect(minimal_db)
    src.execute(
        """
        CREATE TABLE readings (
            date TEXT, id TEXT, temperature REAL, litres_remaining REAL,
            litres_used_since_last REAL, percentage_remaining REAL,
            oil_depth_cm REAL, air_gap_cm REAL, current_ppl REAL,
            cost_used TEXT, cost_to_fill TEXT, heating_degree_days REAL,
            seasonal_efficiency REAL, refill_detected TEXT, leak_detected TEXT,
            raw_flags TEXT, litres_to_order REAL, bars_remaining INTEGER
        )
        """
    )
    src.execute(
        "INSERT INTO readings (date, id, litres_remaining, air_gap_cm) "
        "VALUES (?, ?, ?, ?)",
        ("2026-04-01 12:00:00", "fixture", 800.0, 50.0),
    )
    src.commit()
    src.close()

    report = await migrate(
        src_db=minimal_db,
        src_config=SAMPLE_CONFIG,
        sf=sf,
        settings_service=seeded_settings,
    )
    assert report.rows_per_table["readings"]["copied"] == 1
    # Tables not present in source are recorded as zero.
    assert report.rows_per_table["energy_metrics"]["source"] == 0


async def test_report_path_writes_json(
    sf: async_sessionmaker, seeded_settings, tmp_path: Path
) -> None:
    out = tmp_path / "report.json"
    await migrate(
        src_db=FIXTURE, src_config=SAMPLE_CONFIG,
        sf=sf, settings_service=seeded_settings,
        dry_run=True, report_path=out,
    )
    payload = json.loads(out.read_text())
    assert "rows_per_table" in payload
