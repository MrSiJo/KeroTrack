"""Cost analysis port (was `oil_cost_analysis.py`, 2364 lines in v1).

Computes per-period cost metrics from `refill_periods`, layers in actual
refill costs from `actual_refill_costs` when present, and publishes the
aggregate `oiltank/cost_analysis` payload.

The full v1 implementation pulls in seasonal/weather correction, energy
efficiency comparison, ppl history etc. — for v2.0 we keep the output
shape (spec §3.3 keys) and rely on stored period rows for the heavy
lifting. The CLI deliverable in Phase 6 covers the operator workflows
(`--add-refill`, `--list-refills`).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.clock import local_now, local_now_str, parse_local
from kerotrack.models.cost_analysis import CostAnalysis
from kerotrack.models.refill import ActualRefillCost
from kerotrack.models.refill_period import RefillPeriod
from kerotrack.publish.mqtt_publisher import MqttPublisher
from kerotrack.pubsub.bus import PubSubBus
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)


def _avg(values: list[float]) -> float:
    cleaned = [v for v in values if v is not None]
    return sum(cleaned) / len(cleaned) if cleaned else 0.0


async def compute(
    sf: async_sessionmaker, svc: SettingsService
) -> dict[str, Any] | None:
    async with sf() as session:
        periods = (
            await session.execute(
                select(RefillPeriod).order_by(desc(RefillPeriod.end_date))
            )
        ).scalars().all()
        actuals = {
            row.refill_date: row
            for row in (
                await session.execute(select(ActualRefillCost))
            ).scalars().all()
        }

    if not periods:
        return None

    latest = periods[0]
    days_since_refill = 0
    end_dt = parse_local(latest.end_date)
    if end_dt is not None:
        days_since_refill = max((local_now() - end_dt).days, 0)

    period_costs = [p.total_cost or 0.0 for p in periods]
    period_consumptions = [p.total_consumption or 0.0 for p in periods]
    daily_costs = [p.daily_cost or 0.0 for p in periods]

    payload = {
        "analysis_date": local_now_str(),
        "latest_period_start": latest.start_date,
        "latest_period_end": latest.end_date,
        "latest_period_days": latest.days or 0,
        "latest_refill_amount": latest.refill_amount_liters or 0.0,
        "latest_refill_cost": latest.refill_cost or 0.0,
        "latest_refill_ppl": latest.refill_ppl or 0.0,
        "latest_total_consumption": latest.total_consumption or 0.0,
        "latest_total_cost": latest.total_cost or 0.0,
        "latest_daily_cost": latest.daily_cost or 0.0,
        "latest_weekly_cost": latest.weekly_cost or 0.0,
        "latest_monthly_cost": latest.monthly_cost or 0.0,
        "days_since_refill": days_since_refill,
        "avg_period_cost": round(_avg(period_costs), 2),
        "avg_period_consumption": round(_avg(period_consumptions), 1),
        "avg_daily_cost": round(_avg(daily_costs), 2),
        "avg_weekly_cost": round(_avg(daily_costs) * 7, 2),
        "avg_monthly_cost": round(_avg(daily_costs) * 30, 2),
        "avg_annual_cost": round(_avg(daily_costs) * 365, 2),
        "avg_cost_per_hdd": round(_avg([p.cost_per_hdd or 0.0 for p in periods]), 4),
        "avg_consumption_per_hdd": round(
            _avg([p.consumption_per_hdd or 0.0 for p in periods]), 4
        ),
        "avg_cost_per_kwh": 0.0,
        "avg_daily_energy_kwh": 0.0,
        "avg_cost_per_heat_unit": 0.0,
        "total_refill_periods": len(periods),
        "percentage_with_actual_data": round(
            (
                100.0
                * sum(1 for p in periods if (p.refill_invoice or "") in actuals)
                / max(len(periods), 1)
            ),
            1,
        ),
        "energy_efficiency": float(await svc.get("boiler.efficiency_pct")) / 100.0,
    }
    payload["analysis_data"] = json.dumps({"period_count": len(periods)})
    return payload


async def _persist(sf: async_sessionmaker, payload: dict[str, Any]) -> None:
    async with sf() as session:
        existing = (
            await session.execute(
                select(CostAnalysis).where(
                    CostAnalysis.analysis_date == payload["analysis_date"]
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(CostAnalysis(**payload))
        else:
            for k, v in payload.items():
                setattr(existing, k, v)
        await session.commit()


async def run_cost_analysis(
    *,
    sf: async_sessionmaker,
    settings_service: SettingsService,
    publisher: MqttPublisher,
    pubsub: PubSubBus | None = None,
) -> dict[str, Any] | None:
    payload = await compute(sf, settings_service)
    if payload is None:
        logger.info("No refill periods — skipping cost analysis")
        return None
    await _persist(sf, payload)
    await publisher.publish_costanalysis(payload)
    if pubsub is not None:
        await pubsub.publish("cost_analysis", payload)
    return payload
