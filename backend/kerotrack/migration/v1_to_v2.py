"""v1 SQLite + YAML → v2 migrator."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml as yaml_lib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.migration.yaml_mapping import map_yaml_to_settings
from kerotrack.models.analysis_result import AnalysisResult
from kerotrack.models.cost_analysis import CostAnalysis
from kerotrack.models.energy_metric import EnergyMetric
from kerotrack.models.hdd import HddDatum
from kerotrack.models.reading import Reading
from kerotrack.models.refill import ActualRefillCost
from kerotrack.models.refill_period import RefillPeriod
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)


TABLE_TO_MODEL = {
    "readings": Reading,
    "analysis_results": AnalysisResult,
    "actual_refill_costs": ActualRefillCost,
    "refill_periods": RefillPeriod,
    "hdd_data": HddDatum,
    "energy_metrics": EnergyMetric,
    "cost_analysis": CostAnalysis,
}


@dataclass
class MigrationReport:
    src_db: str
    src_config: str
    dry_run: bool
    forced: bool
    rows_per_table: dict[str, dict[str, int]] = field(default_factory=dict)
    settings_written: list[str] = field(default_factory=list)
    settings_ignored: list[str] = field(default_factory=list)
    settings_missing: list[str] = field(default_factory=list)
    skipped_rows: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "src_db": self.src_db,
            "src_config": self.src_config,
            "dry_run": self.dry_run,
            "forced": self.forced,
            "rows_per_table": self.rows_per_table,
            "settings_written": sorted(self.settings_written),
            "settings_ignored": sorted(self.settings_ignored),
            "settings_missing": sorted(self.settings_missing),
            "skipped_rows": self.skipped_rows,
            "errors": self.errors,
        }


def _open_source(src_db: Path) -> sqlite3.Connection:
    if not src_db.exists():
        raise FileNotFoundError(f"source DB not found: {src_db}")
    uri = f"file:{src_db.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


async def _destination_is_empty(
    sf: async_sessionmaker, table: str
) -> bool:
    model = TABLE_TO_MODEL[table]
    pk_col = next(iter(model.__table__.primary_key.columns))
    async with sf() as session:
        row = (
            await session.execute(select(pk_col).limit(1))
        ).first()
    return row is None


async def migrate(
    *,
    src_db: Path,
    src_config: Path,
    sf: async_sessionmaker,
    settings_service: SettingsService,
    dry_run: bool = False,
    force: bool = False,
    report_path: Path | None = None,
) -> MigrationReport:
    report = MigrationReport(
        src_db=str(src_db), src_config=str(src_config),
        dry_run=dry_run, forced=force,
    )

    # ----- pre-flight ----------------------------------------------------
    src = _open_source(src_db)
    try:
        # 1. Tables to copy (skip those that don't exist in the source).
        for table, model in TABLE_TO_MODEL.items():
            if not _has_table(src, table):
                report.rows_per_table[table] = {"source": 0, "copied": 0, "skipped": 0}
                continue

            # Refuse to merge into a populated destination unless --force.
            if not dry_run and not force:
                if not await _destination_is_empty(sf, table):
                    raise RuntimeError(
                        f"destination table {table} is non-empty; "
                        "rerun with --force to merge"
                    )

            # Project the source column set onto the v2 model's columns.
            src_cols = _table_columns(src, table)
            dst_cols = set(model.__table__.columns.keys())
            common = [c for c in src_cols if c in dst_cols]

            select_sql = f"SELECT {', '.join(common)} FROM {table}"
            cur = src.execute(select_sql)
            rows = cur.fetchall()

            # v1 SQLite tolerated NULL in TEXT PRIMARY KEY columns. v2 won't —
            # filter rows where any PK column is NULL and report them as
            # skipped so the operator can decide whether the upstream bug is
            # worth chasing.
            pk_cols = [
                c.name for c in model.__table__.primary_key.columns
            ]

            valid_rows: list[Any] = []
            null_pk_rows: list[dict[str, Any]] = []
            for row in rows:
                if any(row[c] is None for c in pk_cols if c in row.keys()):
                    null_pk_rows.append(
                        {col: row[col] for col in common if col in row.keys()}
                    )
                    continue
                valid_rows.append(row)

            copied = 0
            skipped = len(null_pk_rows)
            for nr in null_pk_rows:
                report.skipped_rows.append(
                    {"table": table, "error": "null primary key", "row": nr}
                )

            if not dry_run:
                async with sf() as session:
                    for row in valid_rows:
                        values = {col: row[col] for col in common}
                        try:
                            session.add(model(**values))
                        except Exception as exc:  # noqa: BLE001
                            skipped += 1
                            report.skipped_rows.append(
                                {"table": table, "error": str(exc), "row": dict(values)}
                            )
                            continue
                        copied += 1
                    try:
                        await session.commit()
                    except Exception as exc:  # noqa: BLE001
                        await session.rollback()
                        report.errors.append(
                            f"commit failed for {table}: {exc}"
                        )
                        copied = 0
                        skipped += len(valid_rows)
            else:
                copied = len(valid_rows)
            report.rows_per_table[table] = {
                "source": len(rows),
                "copied": copied,
                "skipped": skipped,
            }

        # 2. Settings from YAML.
        if src_config.exists():
            yaml_data = yaml_lib.safe_load(src_config.read_text()) or {}
        else:
            yaml_data = {}
            report.errors.append(f"config not found: {src_config}")

        mapped = map_yaml_to_settings(yaml_data)
        report.settings_ignored = list(mapped.ignored)
        report.settings_missing = list(mapped.missing)
        if not dry_run:
            for key, value in mapped.settings.items():
                try:
                    await settings_service.set(key, value, source="migration")
                    report.settings_written.append(key)
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(
                        f"failed to write setting {key}={value!r}: {exc}"
                    )
        else:
            report.settings_written = list(mapped.settings.keys())
    finally:
        src.close()

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report.to_dict(), indent=2, default=str))

    return report
