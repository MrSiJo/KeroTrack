import json

from sqlalchemy import select

from kerotrack.models.setting import Setting
from kerotrack.models.setting_change import SettingChange
from kerotrack.settings.seeds import migrate_default_values, seed_defaults


async def test_rewrites_only_untouched_old_defaults(sf):
    async with sf() as s:
        await seed_defaults(s)
        rows = {r.key: r for r in (await s.execute(select(Setting))).scalars()}
        rows["schedule.analysis_cron"].value = json.dumps("0 6 * * 0")
        rows["schedule.notifier_cron"].value = json.dumps("0 8 * * 0")
        rows["schedule.cost_analysis_cron"].value = json.dumps("30 5 * * 2")  # customised
        await s.commit()
    async with sf() as s:
        assert await migrate_default_values(s) == 2
    async with sf() as s:
        rows = {r.key: json.loads(r.value) for r in (await s.execute(select(Setting))).scalars()}
        assert rows["schedule.analysis_cron"] == "0 6 * * sun"
        assert rows["schedule.notifier_cron"] == "0 8 * * *"
        assert rows["schedule.cost_analysis_cron"] == "30 5 * * 2"
        changes = (await s.execute(select(SettingChange).where(SettingChange.source == "migration"))).scalars().all()
        assert len(changes) == 2
    async with sf() as s:
        assert await migrate_default_values(s) == 0
