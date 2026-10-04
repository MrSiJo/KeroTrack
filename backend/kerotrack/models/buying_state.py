"""`buying_state` table: the single row buy signal state (Part D).

Row ``id=1`` holds the latest state, the last state an alert was sent for
(so a restart doesn't resend) and the last MQTT payload as JSON.
"""

from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class BuyingState(Base):
    __tablename__ = "buying_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    last_alerted_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Local naive 'YYYY-MM-DD HH:MM:SS'.
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
