"""`energy_metrics` table — per-period kWh + efficiency."""

from __future__ import annotations

from sqlalchemy import Float, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class EnergyMetric(Base):
    __tablename__ = "energy_metrics"

    period_start: Mapped[str] = mapped_column(Text, primary_key=True)
    period_end: Mapped[str] = mapped_column(Text, primary_key=True)
    total_energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivered_energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_per_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_per_useful_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy_efficiency: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_date: Mapped[str | None] = mapped_column(Text, nullable=True)
