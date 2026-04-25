"""Notifier predicate + apprise dispatch."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from kerotrack.notifier.apprise_notifier import (
    is_monthly_run_day,
    is_weekly_run_day,
    run,
)
from kerotrack.models.reading import Reading


pytestmark = pytest.mark.asyncio


def test_is_weekly_run_day_sunday_only() -> None:
    assert is_weekly_run_day(datetime(2026, 4, 26)) is True  # Sunday
    assert is_weekly_run_day(datetime(2026, 4, 27)) is False  # Monday


def test_is_monthly_run_day_first_sunday_only() -> None:
    assert is_monthly_run_day(datetime(2026, 4, 5)) is True  # 5th is Sun in April
    assert is_monthly_run_day(datetime(2026, 4, 12)) is False  # second Sunday
    assert is_monthly_run_day(datetime(2026, 4, 6)) is False  # Monday after first Sun


class _FakeApprise:
    def __init__(self) -> None:
        self.added: list[str] = []
        self.notified: list[dict[str, Any]] = []

    def add(self, url: str) -> None:
        self.added.append(url)

    def notify(self, *, body: str, title: str) -> bool:
        self.notified.append({"body": body, "title": title})
        return True


async def test_run_skips_when_no_apprise_urls(sf, seeded_settings) -> None:
    result = await run(
        sf=sf,
        settings_service=seeded_settings,
        test_mode=True,
        apprise_factory=_FakeApprise,
    )
    assert result.sent is False
    assert "no apprise" in (result.skipped_reason or "").lower()


async def test_run_test_mode_dispatches(sf, seeded_settings) -> None:
    await seeded_settings.set(
        "notifications.apprise_urls", ["gotify://host/token"]
    )
    fake = _FakeApprise()
    result = await run(
        sf=sf,
        settings_service=seeded_settings,
        test_mode=True,
        apprise_factory=lambda: fake,
    )
    assert result.sent is True
    assert result.channels == 1
    assert fake.added == ["gotify://host/token"]
    assert fake.notified


async def test_run_off_day_does_not_send(sf, seeded_settings) -> None:
    await seeded_settings.set(
        "notifications.apprise_urls", ["gotify://host/token"]
    )
    fake = _FakeApprise()
    # 2026-04-27 is a Monday — neither weekly nor monthly.
    result = await run(
        sf=sf,
        settings_service=seeded_settings,
        now=datetime(2026, 4, 27, 8, 0, 0),
        apprise_factory=lambda: fake,
    )
    assert result.sent is False


async def test_run_weekly_sunday_sends(sf, seeded_settings) -> None:
    await seeded_settings.set(
        "notifications.apprise_urls", ["gotify://host/token"]
    )
    async with sf() as session:
        session.add(
            Reading(
                date="2026-04-26 08:00:00",
                id="probe",
                litres_remaining=850.0,
                percentage_remaining=69.0,
                cost_to_fill="100.50",
            )
        )
        await session.commit()
    fake = _FakeApprise()
    result = await run(
        sf=sf,
        settings_service=seeded_settings,
        now=datetime(2026, 4, 26, 8, 0, 0),
        apprise_factory=lambda: fake,
    )
    assert result.sent is True
    assert "Litres remaining" in result.body
    assert "850.0 L" in result.body
