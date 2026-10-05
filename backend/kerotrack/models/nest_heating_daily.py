"""`nest_heating_daily` table: Nest heating hours per local day, from Home Assistant."""

from __future__ import annotations

from sqlalchemy import Float, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class NestHeatingDaily(Base):
    __tablename__ = "nest_heating_daily"

    # Local day 'YYYY-MM-DD'.
    date: Mapped[str] = mapped_column(Text, primary_key=True)
    heating_hours: Mapped[float] = mapped_column(Float, nullable=False)
    # Local naive 'YYYY-MM-DD HH:MM:SS' when the message was stored.
    received_at: Mapped[str] = mapped_column(Text, nullable=False)
