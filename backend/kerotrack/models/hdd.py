"""`hdd_data` table — heating-degree-days, one row per period."""

from __future__ import annotations

from sqlalchemy import Float, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class HddDatum(Base):
    __tablename__ = "hdd_data"

    date: Mapped[str] = mapped_column(Text, primary_key=True)
    hdd: Mapped[float | None] = mapped_column(Float, nullable=True)
