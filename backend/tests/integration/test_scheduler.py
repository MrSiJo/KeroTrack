"""APScheduler service starts, runs jobs, and reloads triggers on settings change."""

from __future__ import annotations

import asyncio

import pytest

from kerotrack.scheduler.service import SchedulerService


pytestmark = pytest.mark.asyncio


async def test_scheduler_starts_with_three_jobs(seeded_settings) -> None:
    calls: list[str] = []

    async def runner(name: str) -> None:
        calls.append(name)

    svc = SchedulerService(settings_service=seeded_settings, runner=runner)
    await svc.start()
    try:
        assert svc.running is True
        ids = {job.id for job in svc._scheduler.get_jobs()}
        assert ids == {"analysis", "cost_analysis", "notifier"}
    finally:
        svc.shutdown()


async def test_scheduler_trigger_now_invokes_runner(seeded_settings) -> None:
    calls: list[str] = []

    async def runner(name: str) -> str:
        calls.append(name)
        return "ok"

    svc = SchedulerService(settings_service=seeded_settings, runner=runner)
    await svc.start()
    try:
        result = await svc.trigger_now("analysis")
        assert result == "ok"
        assert calls == ["analysis"]
    finally:
        svc.shutdown()


async def test_scheduler_reloads_on_setting_change(seeded_settings) -> None:
    async def runner(name: str) -> None:
        return None

    svc = SchedulerService(settings_service=seeded_settings, runner=runner)
    await svc.start()
    try:
        original_trigger = str(
            svc._scheduler.get_job("notifier").trigger
        )
        await seeded_settings.set("schedule.notifier_cron", "30 9 * * 1-5")
        # subscribe runs callbacks synchronously after set; give the loop a tick.
        await asyncio.sleep(0.05)
        new_trigger = str(svc._scheduler.get_job("notifier").trigger)
        assert original_trigger != new_trigger
    finally:
        svc.shutdown()
