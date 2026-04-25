"""Idempotent schema bootstrap.

Brings up every table the v2 system needs:

- v1-compatible: readings, analysis_results, refill_periods, actual_refill_costs,
  hdd_data, energy_metrics, cost_analysis
- v2 additions: settings, setting_changes, users (Phase 2.5)

`ensure_schema` is idempotent — calling it twice on an empty DB and once-then-once
again on a populated DB both end with the same schema and the same row counts.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from kerotrack.models.base import Base

# Importing each model registers the mapped class on `Base.metadata`. Order
# doesn't matter for create_all but we keep them grouped.
from kerotrack.models import setting as _setting  # noqa: F401
from kerotrack.models import setting_change as _setting_change  # noqa: F401
from kerotrack.models import reading as _reading  # noqa: F401
from kerotrack.models import analysis_result as _ar  # noqa: F401
from kerotrack.models import refill as _refill  # noqa: F401
from kerotrack.models import refill_period as _rp  # noqa: F401
from kerotrack.models import hdd as _hdd  # noqa: F401
from kerotrack.models import energy_metric as _em  # noqa: F401
from kerotrack.models import cost_analysis as _ca  # noqa: F401


async def ensure_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
