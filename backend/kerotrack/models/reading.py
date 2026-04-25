"""`readings` table — every Watchman Sonic packet that has come through ingest."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class Reading(Base):
    __tablename__ = "readings"

    # v1 has no PK on readings; (date, id) is unique in practice. Composite PK
    # keeps the migrator's row copy a straight INSERT.
    date: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)

    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    litres_remaining: Mapped[float | None] = mapped_column(Float, nullable=True)
    litres_used_since_last: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentage_remaining: Mapped[float | None] = mapped_column(Float, nullable=True)
    oil_depth_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    air_gap_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_ppl: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per spec §3.1 — KeroDisplay parses this as a string. Store as TEXT.
    cost_to_fill: Mapped[str | None] = mapped_column(Text, nullable=True)
    heating_degree_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    seasonal_efficiency: Mapped[float | None] = mapped_column(Float, nullable=True)
    refill_detected: Mapped[str | None] = mapped_column(Text, nullable=True)
    leak_detected: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_flags: Mapped[str | None] = mapped_column(Text, nullable=True)
    litres_to_order: Mapped[float | None] = mapped_column(Float, nullable=True)
    bars_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
