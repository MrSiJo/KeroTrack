"""`analysis_results` table — per-run aggregate stats from the analysis job."""

from __future__ import annotations

from sqlalchemy import Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    latest_reading_date: Mapped[str] = mapped_column(Text, primary_key=True)
    latest_analysis_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_reading_refill_detected: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    latest_reading_leak_detected: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    days_since_refill: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_consumption_since_refill: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    avg_daily_consumption_l: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_days_remaining: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_empty_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    consumption_per_hdd_l: Mapped[float | None] = mapped_column(Float, nullable=True)
    upcoming_month_hdd: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_daily_consumption_hdd_l: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    estimated_daily_hot_water_consumption_l: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    estimated_daily_heating_consumption_l: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    seasonal_heating_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    remaining_days_empty_hdd: Mapped[float | None] = mapped_column(Float, nullable=True)
    remaining_date_empty_hdd: Mapped[str | None] = mapped_column(Text, nullable=True)
