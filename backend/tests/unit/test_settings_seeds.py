"""Idempotent seed behaviour."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.models.setting import Setting
from kerotrack.settings.schema import SETTINGS_CATALOGUE
from kerotrack.settings.seeds import seed_defaults


pytestmark = pytest.mark.asyncio


async def test_seed_inserts_all_keys_on_empty_db(sf: async_sessionmaker) -> None:
    async with sf() as session:
        inserted = await seed_defaults(session)
    assert inserted == len(SETTINGS_CATALOGUE)
    async with sf() as session:
        keys = set((await session.execute(select(Setting.key))).scalars().all())
    assert keys == set(SETTINGS_CATALOGUE.keys())


async def test_seed_is_idempotent(sf: async_sessionmaker) -> None:
    async with sf() as session:
        first = await seed_defaults(session)
    async with sf() as session:
        second = await seed_defaults(session)
    assert first == len(SETTINGS_CATALOGUE)
    assert second == 0


async def test_seed_does_not_overwrite_operator_change(
    sf: async_sessionmaker,
) -> None:
    from kerotrack.settings.service import SettingsService

    async with sf() as session:
        await seed_defaults(session)
    svc = SettingsService(sf)
    await svc.set("tank.capacity_l", 9999)
    async with sf() as session:
        re_inserted = await seed_defaults(session)
    assert re_inserted == 0
    assert await svc.get("tank.capacity_l") == 9999.0


async def test_seed_drops_retired_keys(sf: async_sessionmaker) -> None:
    """B5: prices.homefuelsdirect_url (and any other RETIRED_KEYS) is
    purged on the next seed run."""
    from sqlalchemy import insert

    from kerotrack.models.base import utc_now_iso
    from kerotrack.settings.seeds import RETIRED_KEYS

    # Pre-seed a retired key as if migrated from an older deployment.
    async with sf() as session:
        await session.execute(
            insert(Setting).values(
                key="prices.homefuelsdirect_url",
                value='"https://homefuelsdirect.example/"',
                value_type="string",
                group_name="prices",
                label="HomeFuelsDirect URL",
                description=None,
                is_secret=0,
                updated_at=utc_now_iso(),
            )
        )
        await session.commit()

    async with sf() as session:
        await seed_defaults(session)
    async with sf() as session:
        keys = set((await session.execute(select(Setting.key))).scalars().all())
    for retired in RETIRED_KEYS:
        assert retired not in keys
