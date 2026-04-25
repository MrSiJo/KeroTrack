"""`refill_periods` table — derived per-refill summaries."""

from __future__ import annotations

from sqlalchemy import Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class RefillPeriod(Base):
    __tablename__ = "refill_periods"

    start_date: Mapped[str] = mapped_column(Text, primary_key=True)
    end_date: Mapped[str] = mapped_column(Text, primary_key=True)
    days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_consumption: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_ppl: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    weekly_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    refill_amount_liters: Mapped[float | None] = mapped_column(Float, nullable=True)
    refill_ppl: Mapped[float | None] = mapped_column(Float, nullable=True)
    refill_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    refill_invoice: Mapped[str | None] = mapped_column(Text, nullable=True)
    refill_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    used_actual_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_hdd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_per_hdd: Mapped[float | None] = mapped_column(Float, nullable=True)
    consumption_per_hdd: Mapped[float | None] = mapped_column(Float, nullable=True)
