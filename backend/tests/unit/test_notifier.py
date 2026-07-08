"""Notifier predicate + apprise dispatch + rich-format body."""

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
    assert is_monthly_run_day(datetime(2026, 4, 5)) is True
    assert is_monthly_run_day(datetime(2026, 4, 12)) is False
    assert is_monthly_run_day(datetime(2026, 4, 6)) is False


class _FakeApprise:
    def __init__(self) -> None:
        self.added: list[str] = []
        self.notified: list[dict[str, Any]] = []

    def add(self, url: str) -> None:
        self.added.append(url)

    def notify(self, *, body: str, title: str, body_format: Any = None) -> bool:
        self.notified.append({"body": body, "title": title, "body_format": body_format})
        return True


def _factory(fake: _FakeApprise):
    def make(urls: list[str]) -> _FakeApprise:
        for u in urls:
            fake.add(u)
        return fake

    return make


async def test_run_skips_when_no_apprise_urls(sf, seeded_settings) -> None:
    result = await run(
        sf=sf,
        settings_service=seeded_settings,
        test_mode=True,
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
        apprise_factory=_factory(fake),
    )
    assert result.sent is True
    assert result.channels == 1
    assert fake.added == ["gotify://host/token"]
    assert fake.notified
    assert result.title.startswith("[TEST]")


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
        apprise_factory=_factory(fake),
    )
    assert result.sent is False


async def test_run_weekly_sunday_sends_rich_format(sf, seeded_settings) -> None:
    await seeded_settings.set(
        "notifications.apprise_urls", ["gotify://host/token"]
    )
    async with sf() as session:
        # Two readings a week apart so refill-aware usage has data.
        session.add(
            Reading(
                date="2026-04-19 08:00:00",
                id="probe",
                litres_remaining=900.0,
                percentage_remaining=73.5,
                current_ppl=78.0,
                refill_detected="n",
            )
        )
        session.add(
            Reading(
                date="2026-04-26 08:00:00",
                id="probe",
                litres_remaining=850.0,
                percentage_remaining=69.0,
                current_ppl=78.5,
                refill_detected="n",
                cost_to_fill="100.50",
            )
        )
        await session.commit()

    fake = _FakeApprise()
    result = await run(
        sf=sf,
        settings_service=seeded_settings,
        now=datetime(2026, 4, 26, 8, 0, 0),
        apprise_factory=_factory(fake),
    )
    assert result.sent is True
    # Rich Markdown format markers from v1
    assert "**Tank Level:**" in result.body
    assert "**Weekly Usage:**" in result.body
    assert "**Trend:**" in result.body
    assert "**Est. Empty:**" in result.body
    assert "850.0 L (69.0%)" in result.body


async def test_weekly_tank_level_skips_noise_suppressed_spike(
    sf, seeded_settings
) -> None:
    """A multipath spike stamped noise_suppressed must not become the
    digest's ⛽ Tank Level — it should agree with the dashboard, which
    already skipped such rows (KERO-H3 drift)."""
    await seeded_settings.set(
        "notifications.apprise_urls", ["gotify://host/token"]
    )
    async with sf() as session:
        session.add(
            Reading(
                date="2026-04-19 08:00:00",
                id="probe",
                litres_remaining=900.0,
                percentage_remaining=73.5,
                current_ppl=78.0,
                refill_detected="n",
            )
        )
        session.add(
            Reading(
                date="2026-04-26 07:00:00",
                id="probe",
                litres_remaining=850.0,
                percentage_remaining=69.0,
                current_ppl=78.5,
                refill_detected="n",
            )
        )
        # Newest row is a suppressed sensor spike — bad litres value.
        session.add(
            Reading(
                date="2026-04-26 07:30:00",
                id="probe",
                litres_remaining=1150.0,
                percentage_remaining=93.9,
                current_ppl=78.5,
                refill_detected="n",
                raw_flags="152:noise_suppressed",
            )
        )
        await session.commit()

    fake = _FakeApprise()
    result = await run(
        sf=sf,
        settings_service=seeded_settings,
        now=datetime(2026, 4, 26, 8, 0, 0),
        apprise_factory=_factory(fake),
    )
    assert result.sent is True
    assert "850.0 L (69.0%)" in result.body
    assert "1150.0" not in result.body


async def test_gotify_url_gets_markdown_format() -> None:
    from kerotrack.notifier.apprise_notifier import _build_apprise
    instance = _build_apprise(["gotify://host/token"])
    urls = list(instance.urls())
    assert urls and "format=markdown" in urls[0]


async def test_gotify_url_with_existing_query_still_gets_markdown() -> None:
    from kerotrack.notifier.apprise_notifier import _build_apprise
    instance = _build_apprise(["gotify://host/token?priority=high"])
    urls = list(instance.urls())
    assert urls and "format=markdown" in urls[0]
