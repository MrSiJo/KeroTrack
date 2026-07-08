"""Daily HDD roll-up — the writer the `hdd_data` table was missing.

Every reading already carries an instantaneous heating-degree-days value
(``max(0, base_temperature - temperature)``, computed at ingest by
``recalc.calculate_hdd``), but nothing in v2 ever wrote to ``hdd_data`` —
the table was frozen at the monthly rows copied by the one-shot v1
migration, so the daily-key lookups in ``analysis/consumption.py`` and
``analysis/cost.py`` almost always missed and every HDD-derived metric
decayed to zero (KERO-H1).

This module aggregates the per-reading values into one ``hdd_data`` row per
local day (the mean of that day's readings) and upserts them. It covers the
full reading history on every run: the GROUP BY is over at most a few tens
of thousands of rows, trivial for SQLite, and it backfills daily rows for
the whole period readings exist. A migrated *monthly* row whose
first-of-month key collides with a day that has readings is overwritten
with the daily value — daily semantics everywhere beats a frozen monthly
lump the daily lookups could never use.

It runs at the start of every scheduled analysis run (see
``consumption.run_analysis``), so ``hdd_data`` is fresh at exactly the
cadence the analysis consumes it. Today's row is a partial-day mean that
gets refreshed on each run until the day rolls over.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.models.hdd import HddDatum
from kerotrack.models.reading import Reading

logger = logging.getLogger(__name__)


async def aggregate_daily_hdd(sf: async_sessionmaker) -> int:
    """Upsert one `hdd_data` row per local day from per-reading HDD values.

    Returns the number of rows inserted or updated (unchanged rows are
    skipped so repeat runs over settled history are near-free).
    """
    day = func.substr(Reading.date, 1, 10)
    stmt = (
        select(day.label("day"), func.avg(Reading.heating_degree_days).label("hdd"))
        .where(Reading.heating_degree_days.is_not(None))
        .group_by(day)
    )
    written = 0
    async with sf() as session:
        aggregated = (await session.execute(stmt)).all()
        if not aggregated:
            return 0
        existing = {
            row.date: row
            for row in (await session.execute(select(HddDatum))).scalars()
        }
        for day_str, hdd in aggregated:
            value = round(float(hdd), 4)
            current = existing.get(day_str)
            if current is None:
                session.add(HddDatum(date=day_str, hdd=value))
                written += 1
            elif current.hdd != value:
                current.hdd = value
                written += 1
        await session.commit()
    if written:
        logger.info("HDD roll-up wrote %d daily rows", written)
    return written
