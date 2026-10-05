"""CLI `import-nest-months` (synthetic data)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack import cli
from kerotrack.ingest.nest import load_nest_monthly


def test_parser_has_import_nest_months() -> None:
    args = cli._build_parser().parse_args(["import-nest-months", "data/nest.csv"])
    assert args.cmd == "import-nest-months"
    assert args.csv == "data/nest.csv"


@pytest.mark.asyncio
async def test_import_prints_count_only(
    sf: async_sessionmaker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    async def _fake_with_session(callback):
        return await callback(sf)

    monkeypatch.setattr(cli, "_with_session", _fake_with_session)
    csv_path = tmp_path / "nest.csv"
    csv_path.write_text(
        "month,heating_hours,source\n2025-01,61.25,report\n2025-02,42.5,prev\n"
        "2025-02,43.5,prev\n",
        encoding="utf-8",
    )
    rc = await cli._import_nest_months(argparse.Namespace(csv=str(csv_path)))
    out = capsys.readouterr()
    assert rc == 0
    import json

    assert json.loads(out.out) == {"imported": 2, "skipped_duplicates": 1}
    assert "61.25" not in out.out + out.err
    assert "2025-01" not in out.out + out.err
    assert await load_nest_monthly(sf) == {"2025-01": 61.25, "2025-02": 42.5}


@pytest.mark.asyncio
async def test_import_bad_csv_returns_2(tmp_path: Path, capsys) -> None:
    csv_path = tmp_path / "nest.csv"
    csv_path.write_text("month,heating_hours,source\n2025-01,99999,report\n", encoding="utf-8")
    rc = await cli._import_nest_months(argparse.Namespace(csv=str(csv_path)))
    assert rc == 2
    assert "99999" not in capsys.readouterr().err


@pytest.mark.asyncio
async def test_import_csv_error_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    import csv

    import kerotrack.ingest.nest as nest

    def _boom(path):
        raise csv.Error("field larger than field limit")

    monkeypatch.setattr(nest, "parse_nest_months_csv", _boom)
    rc = await cli._import_nest_months(argparse.Namespace(csv=str(tmp_path / "x.csv")))
    assert rc == 2
    assert "import-nest-months" in capsys.readouterr().err
