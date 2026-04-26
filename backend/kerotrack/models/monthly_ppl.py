"""`monthly_avg_ppl` table — one-shot historical correction (ONS RPI series).

This is NOT part of the live ingest path. It exists purely so a `kerotrack
rebuild-costs` run can substitute a defensible monthly average when the
recorded `current_ppl` was a stuck scrape value. New deployments don't
need it; this is a unique-to-this-instance correction for the long
HomeFuelsDirect outage in 2025.
"""

from __future__ import annotations

from sqlalchemy import Float, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class MonthlyPpl(Base):
    __tablename__ = "monthly_avg_ppl"

    # Format: ``YYYY-MM`` (matches the ONS series after parsing).
    month: Mapped[str] = mapped_column(Text, primary_key=True)
    ppl: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
