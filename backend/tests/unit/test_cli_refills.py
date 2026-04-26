"""CLI refill subcommands (backlog A7).

Each subcommand wraps existing service calls; tests focus on the
historical-deliveries parser and on the argparse wiring being correct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kerotrack.cli import (
    _build_parser,
    _parse_historical_deliveries,
)


def test_parser_has_refill_subcommands() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        [
            "add-refill",
            "--refill-date",
            "2025-11-01 09:00:00",
            "--volume",
            "420",
            "--ppl",
            "82.5",
            "--total-cost",
            "346.50",
            "--invoice",
            "INV-1",
        ]
    )
    assert args.cmd == "add-refill"
    assert args.refill_date == "2025-11-01 09:00:00"
    assert args.volume == pytest.approx(420)
    assert args.ppl == pytest.approx(82.5)
    assert args.total_cost == pytest.approx(346.50)
    assert args.invoice == "INV-1"

    args = parser.parse_args(["list-refills"])
    assert args.cmd == "list-refills"

    args = parser.parse_args(
        ["delete-refill", "--refill-date", "2025-11-01 09:00:00"]
    )
    assert args.cmd == "delete-refill"

    args = parser.parse_args(["clear-refills", "--yes"])
    assert args.cmd == "clear-refills"
    assert args.yes is True

    args = parser.parse_args(
        ["import-historical", "--path", "data/historical_deliveries.txt"]
    )
    assert args.cmd == "import-historical"
    assert args.path == "data/historical_deliveries.txt"


def test_parse_historical_deliveries(tmp_path: Path) -> None:
    fixture = tmp_path / "historical_deliveries.txt"
    fixture.write_text(
        "Product - Quantity - Service - DeliveryBy - PPL - OrderTotal\n"
        "Premium Kerosene - 500 - Standard - 01/02/2025 - 80.5 - 402.50\n"
        "Premium Kerosene - 1000 - Express - 15/06/2025 - 75.0 - 750.00\n"
        "  \n"
        "malformed line\n"
    )
    deliveries = _parse_historical_deliveries(fixture)
    assert len(deliveries) == 2
    assert deliveries[0]["refill_date"] == "2025-02-01 12:00:00"
    assert deliveries[0]["actual_volume_litres"] == pytest.approx(500)
    assert deliveries[0]["actual_ppl"] == pytest.approx(80.5)
    assert deliveries[0]["total_cost"] == pytest.approx(402.50)
    assert deliveries[1]["refill_date"] == "2025-06-15 12:00:00"


def test_parse_historical_deliveries_missing_file(tmp_path: Path) -> None:
    assert _parse_historical_deliveries(tmp_path / "nope.txt") == []
