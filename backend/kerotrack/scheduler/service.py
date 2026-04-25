"""APScheduler integration with live reload on settings change."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)


_JOB_TO_SETTING = {
    "analysis": "schedule.analysis_cron",
    "cost_analysis": "schedule.cost_analysis_cron",
    "notifier": "schedule.notifier_cron",
}


def _trigger_from_cron(expression: str) -> CronTrigger:
    return CronTrigger.from_crontab(expression)


class SchedulerService:
    def __init__(
        self,
        *,
        settings_service: SettingsService,
        runner: Callable[[str], Awaitable[Any]],
        timezone: str = "Europe/London",
    ) -> None:
        self._svc = settings_service
        self._runner = runner
        self._scheduler = AsyncIOScheduler(timezone=timezone)
        self.running = False

    async def start(self) -> None:
        for name, key in _JOB_TO_SETTING.items():
            expr = await self._svc.get(key)
            self._scheduler.add_job(
                self._wrap(name),
                _trigger_from_cron(expr),
                id=name,
                coalesce=True,
                misfire_grace_time=3600,
                replace_existing=True,
            )
        self._svc.on_change("schedule.*", self.reload)
        self._scheduler.start()
        self.running = True
        logger.info("Scheduler started with %d jobs", len(_JOB_TO_SETTING))

    def shutdown(self) -> None:
        if self.running:
            self._scheduler.shutdown(wait=False)
            self.running = False

    async def reload(self, key: str, old: Any, new: Any) -> None:
        # Find which job this key belongs to and reschedule.
        for name, mapped_key in _JOB_TO_SETTING.items():
            if mapped_key == key:
                logger.info("Rescheduling job %s with cron=%s", name, new)
                self._scheduler.reschedule_job(
                    name, trigger=_trigger_from_cron(str(new))
                )
                return

    async def trigger_now(self, name: str) -> Any:
        return await self._runner(name)

    def _wrap(self, name: str) -> Callable[[], Awaitable[Any]]:
        async def _job() -> Any:
            try:
                return await self._runner(name)
            except Exception:  # noqa: BLE001
                logger.exception("scheduled job %s failed", name)
                return None

        return _job
