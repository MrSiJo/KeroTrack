"""`cost_analysis` table — snapshots of full cost analysis runs."""

from __future__ import annotations

from sqlalchemy import Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class CostAnalysis(Base):
    __tablename__ = "cost_analysis"

    analysis_date: Mapped[str] = mapped_column(Text, primary_key=True)
    latest_period_start: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_period_end: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_refill_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_refill_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_refill_ppl: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_total_consumption: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_total_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_daily_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_weekly_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_monthly_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    days_since_refill: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_period_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_period_consumption: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_daily_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_weekly_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_monthly_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_annual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_cost_per_hdd: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_consumption_per_hdd: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_cost_per_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_daily_energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_cost_per_heat_unit: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_refill_periods: Mapped[int | None] = mapped_column(Integer, nullable=True)
    percentage_with_actual_data: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    energy_efficiency: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_data: Mapped[str | None] = mapped_column(Text, nullable=True)
