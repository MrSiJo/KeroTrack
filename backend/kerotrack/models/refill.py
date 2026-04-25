"""`actual_refill_costs` table — operator-entered refill cost data."""

from __future__ import annotations

from sqlalchemy import Float, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class ActualRefillCost(Base):
    __tablename__ = "actual_refill_costs"

    refill_date: Mapped[str] = mapped_column(Text, primary_key=True)
    actual_volume_litres: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_ppl: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    invoice_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
