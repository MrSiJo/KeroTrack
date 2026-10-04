"""`price_quotes` table: one row per supplier option per poll (Part B)."""

from __future__ import annotations

from sqlalchemy import Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class PriceQuote(Base):
    __tablename__ = "price_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Local naive 'YYYY-MM-DD HH:MM:SS'.
    fetched_at: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    supplier: Mapped[str] = mapped_column(Text, nullable=False)
    # 'quote' (local all-in supplier quote) or 'index' (BoilerJuice national).
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    litres: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    urgent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ppl_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_inc_vat: Mapped[float | None] = mapped_column(Float, nullable=True)
    fees_inc_vat: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ppl_effective: Mapped[float | None] = mapped_column(Float, nullable=True)
    ok: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
