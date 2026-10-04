"""`runway_projection` table: one row per scenario per projection run (Part C)."""

from __future__ import annotations

from sqlalchemy import Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class RunwayProjection(Base):
    __tablename__ = "runway_projection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[str] = mapped_column(Text, nullable=False)
    scenario: Mapped[str] = mapped_column(Text, nullable=False)
    k: Mapped[float] = mapped_column(Float, nullable=False)
    hw_l_per_day: Mapped[float] = mapped_column(Float, nullable=False)
    start_litres: Mapped[float] = mapped_column(Float, nullable=False)
    run_out_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_by_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_order_by_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON list of [YYYY-MM-DD, litres] weekly points.
    series_json: Mapped[str] = mapped_column(Text, nullable=False)
