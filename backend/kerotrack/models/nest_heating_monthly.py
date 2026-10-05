"""`nest_heating_monthly` table: Nest heating hours per calendar month.

``source`` is ``report`` (the month's own Nest Home Report), ``prev`` (the
same month quoted as last year in a later report) or ``daily`` (rolled up
from ``nest_heating_daily``). ``report`` rows are never overwritten by the
daily roll-up.
"""

from __future__ import annotations

from sqlalchemy import Float, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class NestHeatingMonthly(Base):
    __tablename__ = "nest_heating_monthly"

    # 'YYYY-MM'.
    month: Mapped[str] = mapped_column(Text, primary_key=True)
    heating_hours: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
