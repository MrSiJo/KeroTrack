"""Settings service round-trips, type coercion, cache, audit, subscribers."""

from __future__ import annotations

import asyncio

import pytest

from kerotrack.settings.service import SettingError, SettingsService


pytestmark = pytest.mark.asyncio


async def test_round_trip_string(seeded_settings: SettingsService) -> None:
    await seeded_settings.set("currency.symbol", "$")
    assert await seeded_settings.get("currency.symbol") == "$"


async def test_round_trip_int(seeded_settings: SettingsService) -> None:
    await seeded_settings.set("mqtt.port", "1885")
    assert await seeded_settings.get("mqtt.port") == 1885


async def test_round_trip_float(seeded_settings: SettingsService) -> None:
    await seeded_settings.set("tank.capacity_l", "1500.5")
    assert await seeded_settings.get("tank.capacity_l") == 1500.5


async def test_round_trip_bool(seeded_settings: SettingsService) -> None:
    await seeded_settings.set("notifications.weekly_enabled", "false")
    assert await seeded_settings.get("notifications.weekly_enabled") is False


async def test_round_trip_json_list(seeded_settings: SettingsService) -> None:
    urls = ["gotify://host/token", "mailto://test@example.com"]
    await seeded_settings.set("notifications.apprise_urls", urls)
    assert await seeded_settings.get("notifications.apprise_urls") == urls


async def test_round_trip_json_string_form(seeded_settings: SettingsService) -> None:
    await seeded_settings.set(
        "notifications.apprise_urls", '["one", "two"]'
    )
    assert await seeded_settings.get("notifications.apprise_urls") == ["one", "two"]


async def test_round_trip_secret(seeded_settings: SettingsService) -> None:
    await seeded_settings.set("mqtt.password", "hunter2")
    assert await seeded_settings.get("mqtt.password") == "hunter2"


async def test_round_trip_cron(seeded_settings: SettingsService) -> None:
    await seeded_settings.set("schedule.notifier_cron", "30 7 * * 1-5")
    assert await seeded_settings.get("schedule.notifier_cron") == "30 7 * * 1-5"


async def test_set_unknown_key_raises(seeded_settings: SettingsService) -> None:
    with pytest.raises(SettingError) as ei:
        await seeded_settings.set("not.a.key", 42)
    assert ei.value.code == "unknown_setting"


async def test_invalid_int_raises(seeded_settings: SettingsService) -> None:
    with pytest.raises(SettingError) as ei:
        await seeded_settings.set("mqtt.port", "abc")
    assert ei.value.code == "invalid_int"


async def test_invalid_cron_raises(seeded_settings: SettingsService) -> None:
    with pytest.raises(SettingError) as ei:
        await seeded_settings.set("schedule.notifier_cron", "not a cron")
    assert ei.value.code == "invalid_cron"


async def test_out_of_range_raises(seeded_settings: SettingsService) -> None:
    with pytest.raises(SettingError) as ei:
        await seeded_settings.set("analysis.ema_alpha", 2.0)
    assert ei.value.code == "out_of_range"


async def test_cache_invalidated_on_set(seeded_settings: SettingsService) -> None:
    assert await seeded_settings.get("tank.capacity_l") == 1225.0
    await seeded_settings.set("tank.capacity_l", 9999)
    assert await seeded_settings.get("tank.capacity_l") == 9999.0


async def test_subscribe_fires_on_change(seeded_settings: SettingsService) -> None:
    seen: list[tuple[str, object, object]] = []

    async def cb(key: str, old: object, new: object) -> None:
        seen.append((key, old, new))

    seeded_settings.on_change("schedule.*", cb)
    await seeded_settings.set("schedule.notifier_cron", "0 9 * * *")
    assert seen and seen[0][0] == "schedule.notifier_cron"
    assert seen[0][2] == "0 9 * * *"


async def test_subscribe_pattern_filters_unrelated_keys(
    seeded_settings: SettingsService,
) -> None:
    seen: list[str] = []

    async def cb(key: str, old: object, new: object) -> None:
        seen.append(key)

    seeded_settings.on_change("mqtt.*", cb)
    await seeded_settings.set("schedule.notifier_cron", "0 9 * * *")
    assert seen == []


async def test_reset_returns_default(seeded_settings: SettingsService) -> None:
    await seeded_settings.set("tank.capacity_l", 1500)
    await seeded_settings.reset("tank.capacity_l")
    assert await seeded_settings.get("tank.capacity_l") == 1225.0


async def test_changes_log_grows_on_set(seeded_settings: SettingsService) -> None:
    before = len(await seeded_settings.changes(limit=1000))
    await seeded_settings.set("currency.symbol", "$")
    after = len(await seeded_settings.changes(limit=1000))
    assert after == before + 1


async def test_secret_audit_log_redacts_value(
    seeded_settings: SettingsService,
) -> None:
    await seeded_settings.set("mqtt.password", "hunter2")
    changes = await seeded_settings.changes(key="mqtt.password", limit=10)
    assert any(c["new_value"] == "***" for c in changes)
    assert all("hunter2" not in (c["new_value"] or "") for c in changes)


async def test_all_redacts_secrets(seeded_settings: SettingsService) -> None:
    await seeded_settings.set("mqtt.password", "hunter2")
    rows = await seeded_settings.all()
    pw_row = next(r for r in rows if r["key"] == "mqtt.password")
    assert pw_row["value"] == "********"
