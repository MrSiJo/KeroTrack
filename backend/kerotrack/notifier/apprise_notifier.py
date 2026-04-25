"""Notifier port (was v1 `notifier.py`).

Predicate matches v1: weekly summary every Sunday + monthly summary on the
first Sunday. Apprise URLs come from settings. Refill-aware totals identical
to v1 — read from `refill_periods`.

A `test_mode=True` call always sends, regardless of the day-of-month
predicate, so the operator can verify the channel from the admin endpoint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable

import apprise
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.models.reading import Reading
from kerotrack.models.refill_period import RefillPeriod
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)


def is_weekly_run_day(now: datetime) -> bool:
    return now.weekday() == 6  # Sunday


def is_monthly_run_day(now: datetime) -> bool:
    return now.weekday() == 6 and now.day <= 7  # first Sunday


@dataclass
class NotifierResult:
    sent: bool
    channels: int
    title: str
    body: str
    skipped_reason: str | None = None


def _format_body(level: dict[str, object], cost_summary: dict[str, object] | None) -> str:
    lines = [
        f"Litres remaining: {level.get('litres_remaining')} L",
        f"Percentage: {level.get('percentage_remaining')} %",
        f"Cost to fill: {level.get('cost_to_fill')}",
    ]
    if cost_summary:
        lines.append("")
        lines.append(f"Avg daily cost: {cost_summary.get('avg_daily_cost')}")
        lines.append(f"Avg monthly cost: {cost_summary.get('avg_monthly_cost')}")
    return "\n".join(lines)


async def _level_snapshot(sf: async_sessionmaker) -> dict[str, object] | None:
    async with sf() as session:
        row = (
            await session.execute(
                select(Reading).order_by(desc(Reading.date)).limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "date": row.date,
        "litres_remaining": row.litres_remaining,
        "percentage_remaining": row.percentage_remaining,
        "cost_to_fill": row.cost_to_fill,
    }


async def _cost_summary(sf: async_sessionmaker) -> dict[str, object] | None:
    async with sf() as session:
        row = (
            await session.execute(
                select(RefillPeriod).order_by(desc(RefillPeriod.end_date)).limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "avg_daily_cost": row.daily_cost,
        "avg_monthly_cost": row.monthly_cost,
    }


async def run(
    *,
    sf: async_sessionmaker,
    settings_service: SettingsService,
    test_mode: bool = False,
    now: datetime | None = None,
    apprise_factory: Callable[[], apprise.Apprise] | None = None,
) -> NotifierResult:
    """Run the notifier predicate and dispatch a summary.

    `apprise_factory` is the seam tests use to inject a recording instance.
    """
    now = now or datetime.utcnow()
    weekly = bool(await settings_service.get("notifications.weekly_enabled"))
    monthly = bool(await settings_service.get("notifications.monthly_enabled"))

    if test_mode:
        title_prefix = "Test"
        is_weekly = True
        is_monthly = True
    else:
        is_weekly = weekly and is_weekly_run_day(now)
        is_monthly = monthly and is_monthly_run_day(now)
        title_prefix = (
            "Monthly summary"
            if is_monthly
            else "Weekly summary"
            if is_weekly
            else None
        )

    if not (is_weekly or is_monthly):
        return NotifierResult(
            sent=False,
            channels=0,
            title="",
            body="",
            skipped_reason="not a scheduled run day",
        )

    urls = await settings_service.get("notifications.apprise_urls")
    if not urls:
        return NotifierResult(
            sent=False,
            channels=0,
            title="",
            body="",
            skipped_reason="no apprise URLs configured",
        )

    level = await _level_snapshot(sf)
    summary = await _cost_summary(sf)
    title = f"KeroTrack {title_prefix or 'summary'}"
    body = _format_body(level or {"litres_remaining": "?"}, summary)

    instance = apprise_factory() if apprise_factory else apprise.Apprise()
    for url in urls:
        instance.add(url)
    ok = bool(instance.notify(body=body, title=title))
    return NotifierResult(
        sent=ok,
        channels=len(urls),
        title=title,
        body=body,
        skipped_reason=None,
    )
