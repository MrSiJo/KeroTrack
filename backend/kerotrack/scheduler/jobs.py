"""Scheduled job definitions — thin wrappers over each domain module."""

from __future__ import annotations

import logging
from typing import Any

from kerotrack.analysis.consumption import run_analysis as _run_analysis
from kerotrack.analysis.cost import run_cost_analysis as _run_cost_analysis
from kerotrack.buying.service import run_buying
from kerotrack.ingest.raw_capture import sweep_raw_captures
from kerotrack.notifier.apprise_notifier import run as _run_notifier

logger = logging.getLogger(__name__)


# "buying" is the scheduled run (frequent providers), "buying_daily_quotes"
# the once a day run for providers that need an email, and "buying_all" the
# manual "Check prices now" run that polls every configured provider.
JOB_NAMES = (
    "analysis",
    "cost_analysis",
    "notifier",
    "buying",
    "buying_daily_quotes",
    "buying_all",
)
_BUYING_CADENCE = {"buying": "frequent", "buying_daily_quotes": "daily", "buying_all": None}


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
    if name in _BUYING_CADENCE:
        # MQTT is optional for this job: run_buying skips the publish
        # when no publisher is available. The daily quotes run leaves the
        # national index to the main runs.
        return await run_buying(
            sf=sf,
            settings_service=svc,
            publisher=publisher,
            prices=None if name == "buying_daily_quotes" else getattr(app_state, "prices", None),
            cadence=_BUYING_CADENCE[name],
        )
    raise ValueError(f"unknown job: {name}")
