"""`raw_captures` table — verbatim archive of inbound Watchman Sonic MQTT
payloads.

Captured alongside each recalc in ingest so the `rssi`/`status` history the
`readings` table discards stays reviewable after the fact. OpenMQTTGateway
on the LilyGO publishes without the retain flag, so the broker keeps no
history of its own — this table is the durable record.
"""

from __future__ import annotations

from sqlalchemy import Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base


class RawCapture(Base):
    __tablename__ = "raw_captures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Our ingest wall-clock (local time), so true broadcast cadence can be
    # measured independent of the sensor's self-reported `time`.
    received_at: Mapped[str] = mapped_column(Text, index=True)
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The payload's own timestamp (== readings.date) — a soft join key back
    # to the derived reading.
    sensor_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    rssi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    depth_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The full original payload, verbatim, for any field not promoted above.
    raw_json: Mapped[str] = mapped_column(Text)
