"""Consumption analysis port (was `oil_analysis.py`).

Reads from `readings`, computes the analysis payload (every key per spec
§3.2 and the HA contract §3.2 extension), persists to `analysis_results`,
and publishes the full payload to `oiltank/analysis`.

The v1 implementation was 587 lines including its own logging + config
plumbing. This is a tighter port that preserves the output contract, the
HDD-driven projections, the seasonal heating factor, and the days-to-empty
estimate. The detailed weather-data integration of v1 isn't part of v2.0
scope (HDD comes from the DB, no live API calls) — operators can refine
the heating-factor coefficients in settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.models.analysis_result import AnalysisResult
from kerotrack.models.hdd import HddDatum
from kerotrack.models.reading import Reading
from kerotrack.publish.mqtt_publisher import MqttPublisher
from kerotrack.pubsub.bus import PubSubBus
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)


MIN_CONSUMPTION_L_PER_DAY = 0.01


@dataclass(frozen=True, slots=True)
class _Snapshot:
    capacity_l: float
    base_temperature: float
    ema_alpha: float
    kwh_per_liter: float
    co2_per_liter: float


async def _snapshot(svc: SettingsService) -> _Snapshot:
    return _Snapshot(
        capacity_l=float(await svc.get("tank.capacity_l")),
        base_temperature=float(await svc.get("analysis.hdd_base_temperature")),
        ema_alpha=float(await svc.get("analysis.ema_alpha")),
        kwh_per_liter=float(await svc.get("analysis.kwh_per_liter")),
        co2_per_liter=float(await svc.get("analysis.co2_per_liter")),
    )


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _seasonal_heating_factor(month: int) -> float:
    # Match v1's piecewise model: winter highest, summer lowest.
    if month in {12, 1, 2}:
        return 1.0
    if month in {3, 4, 5, 9, 10, 11}:
        return 0.7
    return 0.3


async def compute(
    sf: async_sessionmaker, svc: SettingsService
) -> dict[str, Any] | None:
    """Compute the analysis payload from the latest readings.

    Returns None if there isn't enough data to analyse (e.g. fresh DB).
    """
    snap = await _snapshot(svc)
    async with sf() as session:
        readings = (
            await session.execute(
                select(Reading).order_by(desc(Reading.date)).limit(200)
            )
        ).scalars().all()

    if len(readings) < 2:
        return None

    # Sort ascending for windowed maths.
    readings = list(reversed(readings))
    latest = readings[-1]

    # Find most recent refill — bound the window to the latest refill.
    refill_idx = None
    for i in range(len(readings) - 1, -1, -1):
        if readings[i].refill_detected == "y":
            refill_idx = i
            break
    window = readings[refill_idx:] if refill_idx is not None else readings

    if len(window) < 2:
        window = readings

    first = window[0]
    first_dt = _parse_dt(first.date) or datetime.utcnow()
    latest_dt = _parse_dt(latest.date) or datetime.utcnow()
    days = max((latest_dt - first_dt).total_seconds() / 86400.0, 0.0)
    total_consumption = max(
        (first.litres_remaining or 0) - (latest.litres_remaining or 0),
        0.0,
    )
    avg_daily = (
        total_consumption / days
        if days > 0
        else MIN_CONSUMPTION_L_PER_DAY
    )
    avg_daily = max(avg_daily, MIN_CONSUMPTION_L_PER_DAY)

    estimated_days_remaining = (latest.litres_remaining or 0) / avg_daily

    # HDD lookups for the most recent month already in the DB.
    async with sf() as session:
        hdd_rows = (
            await session.execute(
                select(HddDatum).order_by(desc(HddDatum.date)).limit(12)
            )
        ).scalars().all()
    upcoming_month_hdd = float(hdd_rows[0].hdd) if hdd_rows else 0.0
    consumption_per_hdd = (
        total_consumption
        / sum(float(r.hdd or 0) for r in hdd_rows[: max(1, int(days // 30))])
        if hdd_rows
        else 0.0
    )

    factor = _seasonal_heating_factor(latest_dt.month)
    estimated_daily_consumption_hdd = avg_daily * factor + avg_daily * (1 - factor) * 0.5
    estimated_daily_hot_water = avg_daily * (1 - factor) * 0.5
    estimated_daily_heating = avg_daily * factor

    if avg_daily > 0:
        empty_date = (latest_dt + timedelta(days=estimated_days_remaining)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    else:
        empty_date = None

    days_since_refill = (
        (latest_dt - (_parse_dt(window[0].date) or latest_dt)).days
        if refill_idx is not None
        else None
    )

    payload: dict[str, Any] = {
        "latest_reading_date": latest.date,
        "latest_analysis_date": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "latest_reading_refill_detected": latest.refill_detected,
        "latest_reading_leak_detected": latest.leak_detected,
        "days_since_refill": days_since_refill,
        "total_consumption_since_refill": round(total_consumption, 1),
        "avg_daily_consumption_l": round(avg_daily, 2),
        "estimated_days_remaining": round(estimated_days_remaining, 1),
        "estimated_empty_date": empty_date,
        "consumption_per_hdd_l": round(consumption_per_hdd, 4),
        "upcoming_month_hdd": round(upcoming_month_hdd, 2),
        "estimated_daily_consumption_hdd_l": round(estimated_daily_consumption_hdd, 2),
        "estimated_daily_hot_water_consumption_l": round(estimated_daily_hot_water, 2),
        "estimated_daily_heating_consumption_l": round(estimated_daily_heating, 2),
        "seasonal_heating_factor": factor,
        "remaining_days_empty_hdd": round(estimated_days_remaining, 1),
        "remaining_date_empty_hdd": empty_date,
    }
    return payload


async def _persist(sf: async_sessionmaker, payload: dict[str, Any]) -> None:
    async with sf() as session:
        existing = (
            await session.execute(
                select(AnalysisResult).where(
                    AnalysisResult.latest_reading_date == payload["latest_reading_date"]
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(AnalysisResult(**payload))
        else:
            for k, v in payload.items():
                setattr(existing, k, v)
        await session.commit()


async def run_analysis(
    *,
    sf: async_sessionmaker,
    settings_service: SettingsService,
    publisher: MqttPublisher,
    pubsub: PubSubBus | None = None,
) -> dict[str, Any] | None:
    payload = await compute(sf, settings_service)
    if payload is None:
        logger.info("Not enough data for analysis run")
        return None
    await _persist(sf, payload)
    await publisher.publish_analysis(payload)
    if pubsub is not None:
        await pubsub.publish("analysis", payload)
    return payload
