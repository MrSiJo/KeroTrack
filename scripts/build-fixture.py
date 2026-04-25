"""Build a sanitised v1 SQLite fixture for the test suite.

Reads the developer's local copy of the production v1 DB at
`legacy/KeroTrack_data.db`, redacts the sensor `id`, free-text fields,
and any operator-supplied refill notes, then writes a small representative
slice to `backend/tests/fixtures/v1_sample.db`.

Run once whenever the v1 schema or representative data changes.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "legacy" / "KeroTrack_data.db"
DST = REPO / "backend" / "tests" / "fixtures" / "v1_sample.db"

# How many rows to keep per table — enough to span at least 3 refill periods
# plus an anomaly day, but small enough to commit comfortably (<50 KB target).
ROW_LIMITS: dict[str, int] = {
    "readings": 200,
    "analysis_results": 50,
    "refill_periods": 9,
    "actual_refill_costs": 0,
    "hdd_data": 12,
    "energy_metrics": 2,
    "cost_analysis": 11,
}

REDACTED_ID = "fixture-sensor"
REDACTED_TEXT = "fixture-redacted"


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cur.fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _create_table_sql(src: sqlite3.Connection, table: str) -> str | None:
    cur = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _sanitise(table: str, columns: list[str], row: tuple) -> tuple:
    redacted = list(row)
    name_to_idx = {c: i for i, c in enumerate(columns)}

    if "id" in name_to_idx:
        redacted[name_to_idx["id"]] = REDACTED_ID
    for free_text in ("refill_invoice", "refill_notes", "notes", "invoice_ref",
                      "order_ref"):
        if free_text in name_to_idx and redacted[name_to_idx[free_text]]:
            redacted[name_to_idx[free_text]] = REDACTED_TEXT
    return tuple(redacted)


def main() -> int:
    if not SRC.exists():
        print(f"missing source: {SRC}", file=sys.stderr)
        return 1
    DST.parent.mkdir(parents=True, exist_ok=True)
    if DST.exists():
        DST.unlink()

    src = sqlite3.connect(f"file:{SRC.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(DST)

    try:
        for table, limit in ROW_LIMITS.items():
            if not _has_table(src, table):
                continue
            ddl = _create_table_sql(src, table)
            if ddl is None:
                continue
            dst.execute(ddl)

            cols = _columns(src, table)
            placeholders = ", ".join("?" * len(cols))
            select_clause = ", ".join(cols)

            # Pick representative rows: most recent N by date if there is one.
            order = " ORDER BY date DESC" if "date" in cols else ""
            src_rows = list(
                src.execute(
                    f"SELECT {select_clause} FROM {table}{order} LIMIT ?",
                    (limit,),
                )
            )
            sanitised = [_sanitise(table, cols, row) for row in src_rows]
            dst.executemany(
                f"INSERT INTO {table} ({select_clause}) VALUES ({placeholders})",
                sanitised,
            )
        dst.commit()
    finally:
        dst.close()
        src.close()

    print(f"wrote {DST} ({DST.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
