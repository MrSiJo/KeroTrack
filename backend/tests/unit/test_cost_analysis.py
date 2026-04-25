"""Cost analysis golden-path."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.analysis.cost import compute, run_cost_analysis
from kerotrack.models.refill_period import RefillPeriod
from kerotrack.publish.mqtt_publisher import MqttPublisher
from kerotrack.pubsub.bus import PubSubBus


pytestmark = pytest.mark.asyncio


REQUIRED_KEYS = {
    "analysis_date",
    "latest_period_start",
    "latest_period_end",
    "latest_period_days",
    "latest_refill_amount",
    "latest_refill_cost",
    "latest_refill_ppl",
    "latest_total_consumption",
    "latest_total_cost",
    "latest_daily_cost",
    "latest_weekly_cost",
    "latest_monthly_cost",
    "days_since_refill",
    "avg_period_cost",
    "avg_period_consumption",
    "avg_daily_cost",
    "avg_weekly_cost",
    "avg_monthly_cost",
    "avg_annual_cost",
    "avg_cost_per_hdd",
    "avg_consumption_per_hdd",
    "avg_cost_per_kwh",
    "avg_daily_energy_kwh",
    "avg_cost_per_heat_unit",
    "total_refill_periods",
    "percentage_with_actual_data",
    "energy_efficiency",
    "analysis_data",
}


async def _seed_periods(sf: async_sessionmaker) -> None:
    async with sf() as session:
        for i in range(3):
            session.add(
                RefillPeriod(
                    start_date=f"2025-{i + 1:02d}-01 00:00:00",
                    end_date=f"2025-{i + 2:02d}-01 00:00:00",
                    days=30,
                    total_consumption=300.0 - i * 10,
                    total_cost=200.0 + i * 5,
                    daily_cost=6.5 + i * 0.1,
                    weekly_cost=45.5,
                    monthly_cost=200.0,
                    refill_amount_liters=400.0,
                    refill_ppl=80.0,
                    refill_cost=320.0,
                )
            )
        await session.commit()


async def test_cost_compute_returns_full_payload(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_periods(sf)
    payload = await compute(sf, seeded_settings)
    assert payload is not None
    assert REQUIRED_KEYS.issubset(payload.keys())


async def test_cost_compute_returns_none_without_periods(
    sf: async_sessionmaker, seeded_settings
) -> None:
    assert await compute(sf, seeded_settings) is None


async def test_run_cost_analysis_publishes_to_correct_topic(
    sf: async_sessionmaker, seeded_settings
) -> None:
    await _seed_periods(sf)

    class Recorder:
        calls = []

        async def publish(self, topic, body, *, qos=0, retain=False):
            type(self).calls.append((topic, body, retain))

    rec = Recorder()
    publisher = MqttPublisher(client=rec)
    payload = await run_cost_analysis(
        sf=sf, settings_service=seeded_settings, publisher=publisher
    )
    assert payload is not None
    assert Recorder.calls[0][0] == "oiltank/cost_analysis"
