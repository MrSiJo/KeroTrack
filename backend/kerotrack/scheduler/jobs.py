"""Scheduled job definitions — thin wrappers over each domain module."""

from __future__ import annotations

import logging
from typing import Any

from kerotrack.analysis.consumption import run_analysis as _run_analysis
from kerotrack.analysis.cost import run_cost_analysis as _run_cost_analysis
from kerotrack.ingest.raw_capture import sweep_raw_captures
from kerotrack.notifier.apprise_notifier import run as _run_notifier

logger = logging.getLogger(__name__)


JOB_NAMES = ("analysis", "cost_analysis", "notifier")


async def run_job(name: str, *, app_state) -> Any:
    sf = app_state.session_factory
    svc = app_state.settings_service
    publisher = getattr(app_state, "publisher", None)
    pubsub = getattr(app_state, "pubsub", None)

    if name == "analysis":
        if publisher is None:
            raise RuntimeError("publisher not initialised")
        return await _run_analysis(
            sf=sf, settings_service=svc, publisher=publisher, pubsub=pubsub
        )
    if name == "cost_analysis":
        if publisher is None:
            raise RuntimeError("publisher not initialised")
        result = await _run_cost_analysis(
            sf=sf, settings_service=svc, publisher=publisher, pubsub=pubsub
        )
        # Weekly retention sweep piggybacks on this job's cadence — a
        # failure must not fail the cost analysis itself (KERO-L5).
        try:
            report = await sweep_raw_captures(sf)
            if report["deleted"]:
                logger.info(
                    "Retention sweep deleted %d raw captures before %s",
                    report["deleted"],
                    report["before"],
                )
        except Exception:  # noqa: BLE001
            logger.exception("raw-capture retention sweep failed")
        return result
    if name == "notifier":
        return await _run_notifier(sf=sf, settings_service=svc)
    raise ValueError(f"unknown job: {name}")
