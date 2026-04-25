"""Scheduled job definitions — thin wrappers over each domain module."""

from __future__ import annotations

import logging
from typing import Any

from kerotrack.analysis.consumption import run_analysis as _run_analysis
from kerotrack.analysis.cost import run_cost_analysis as _run_cost_analysis
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
        return await _run_cost_analysis(
            sf=sf, settings_service=svc, publisher=publisher, pubsub=pubsub
        )
    if name == "notifier":
        return await _run_notifier(sf=sf, settings_service=svc)
    raise ValueError(f"unknown job: {name}")
