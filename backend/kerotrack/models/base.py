"""Shared declarative base + helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with second precision."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
