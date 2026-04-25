"""`setting_changes` table — audit log for every settings mutation."""

from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from kerotrack.models.base import Base, utc_now_iso


class SettingChange(Base):
    __tablename__ = "setting_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String, nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[str] = mapped_column(
        String, nullable=False, default=utc_now_iso
    )
    source: Mapped[str] = mapped_column(String, nullable=False)


Index("idx_setting_changes_key", SettingChange.key)
