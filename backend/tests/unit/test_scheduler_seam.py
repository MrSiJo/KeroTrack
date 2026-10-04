from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from kerotrack.notifier.apprise_notifier import is_weekly_run_day
from kerotrack.settings.schema import SETTINGS_CATALOGUE

TZ = ZoneInfo("Europe/London")


def _fires(expr, start, days):
    trig = CronTrigger.from_crontab(expr, timezone=TZ)
    out, prev, now = [], None, start
    end = start + timedelta(days=days)
    while True:
        nxt = trig.get_next_fire_time(prev, now)
        if nxt is None or nxt > end:
            return out
        out.append(nxt)
        prev = nxt
        now = nxt + timedelta(seconds=1)


def test_notifier_default_hits_a_sunday_every_week():
    expr = SETTINGS_CATALOGUE["schedule.notifier_cron"].default
    for offset in range(7):
        start = datetime(2026, 10, 5, tzinfo=TZ) + timedelta(days=offset)
        fires = _fires(expr, start, 7)
        assert any(is_weekly_run_day(f.replace(tzinfo=None)) for f in fires)


def test_weekly_jobs_fire_on_sunday():
    for key in ("schedule.analysis_cron", "schedule.cost_analysis_cron"):
        fires = _fires(SETTINGS_CATALOGUE[key].default, datetime(2026, 10, 5, tzinfo=TZ), 14)
        assert fires and all(f.weekday() == 6 for f in fires)


def test_buying_cron_fires_daily():
    fires = _fires(SETTINGS_CATALOGUE["schedule.buying_cron"].default, datetime(2026, 10, 5, tzinfo=TZ), 3)
    assert len(fires) == 6
