"""Nest heating hours: MQTT daily ingest, monthly roll-up and CSV back-fill.

Home Assistant publishes one retained message a day to
``mqtt.topic_nest_heating``: ``{"date": "YYYY-MM-DD", "heating_hours": 1.25}``.
Each valid message upserts ``nest_heating_daily``; once a month holds at
least ``MIN_DAILY_ROWS_FOR_MONTH`` daily rows its total is rolled up into
``nest_heating_monthly`` with source ``daily``, unless that month already
has a ``report`` row (imported from the Nest Home Report, never overwritten).

Payload values are never logged; only counts and reasons.
"""

from __future__ import annotations

import calendar
import csv
import logging
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.clock import local_now_str
from kerotrack.models.nest_heating_daily import NestHeatingDaily
from kerotrack.models.nest_heating_monthly import NestHeatingMonthly

logger = logging.getLogger(__name__)

MIN_DAILY_ROWS_FOR_MONTH = 25
MAX_DAILY_HOURS = 24.0
SOURCES = frozenset({"report", "prev", "daily"})
SOURCE_REPORT = "report"
SOURCE_DAILY = "daily"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_CSV_COLUMNS = ("month", "heating_hours", "source")


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def parse_nest_payload(raw: Any) -> tuple[date, float] | None:
    """``(day, heating_hours)`` for a valid payload, else None."""
    if not isinstance(raw, dict):
        return None
    day_raw = raw.get("date")
    if not isinstance(day_raw, str) or not _DATE_RE.match(day_raw):
        return None
    try:
        day = date.fromisoformat(day_raw)
    except ValueError:
        return None
    hours = _finite_number(raw.get("heating_hours"))
    if hours is None or not 0.0 <= hours <= MAX_DAILY_HOURS:
        return None
    return day, hours


async def _roll_up_month(session, month: str) -> None:
    rows = (
        await session.execute(
            select(func.count(), func.sum(NestHeatingDaily.heating_hours)).where(
                NestHeatingDaily.date.like(f"{month}-%")
            )
        )
    ).one()
    count, total = int(rows[0] or 0), float(rows[1] or 0.0)
    if count < MIN_DAILY_ROWS_FOR_MONTH:
        return
    existing = await session.get(NestHeatingMonthly, month)
    if existing is not None and existing.source == SOURCE_REPORT:
        return
    year, mon = (int(p) for p in month.split("-"))
    days_in_month = calendar.monthrange(year, mon)[1]
    # Scale the days present to the whole month (a missed message or two
    # shouldn't read as a month with less heating).
    hours = total * days_in_month / min(count, days_in_month)
    if existing is None:
        session.add(NestHeatingMonthly(month=month, heating_hours=hours, source=SOURCE_DAILY))
    else:
        existing.heating_hours = hours
        existing.source = SOURCE_DAILY


async def store_nest_daily(
    sf: async_sessionmaker, day: str, hours: float, *, received_at: str | None = None
) -> None:
    """Upsert one daily row, then refresh that month's roll-up."""
    stamp = received_at or local_now_str()
    async with sf() as session:
        row = await session.get(NestHeatingDaily, day)
        if row is None:
            session.add(NestHeatingDaily(date=day, heating_hours=hours, received_at=stamp))
        else:
            row.heating_hours = hours
            row.received_at = stamp
        await session.flush()
        await _roll_up_month(session, day[:7])
        await session.commit()


async def handle_nest_payload(raw: Any, *, sf: async_sessionmaker) -> bool:
    """Validate and store one MQTT message. Invalid payloads are dropped."""
    parsed = parse_nest_payload(raw)
    if parsed is None:
        logger.warning("nest heating: invalid payload dropped (expected ISO date and 0-24 hours)")
        return False
    day, hours = parsed
    await store_nest_daily(sf, day.isoformat(), hours)
    logger.info("nest heating: stored 1 daily row")
    return True


def parse_nest_months_csv(path: Path) -> list[tuple[str, float, str]]:
    """Read ``month,heating_hours,source`` rows. Raises ValueError naming the
    first bad line number (never its contents)."""
    out: list[tuple[str, float, str]] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = tuple((name or "").strip() for name in (reader.fieldnames or ()))
        if not set(_CSV_COLUMNS) <= set(header):
            raise ValueError("CSV needs the columns month,heating_hours,source")
        for row in reader:
            values = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}
            if not any(values.values()):
                continue
            month = values.get("month", "")
            source = values.get("source", "")
            hours = _finite_number(values.get("heating_hours"))
            line = reader.line_num
            if not _MONTH_RE.match(month) or not 1 <= int(month[5:7]) <= 12:
                raise ValueError(f"line {line}: month must be YYYY-MM")
            max_hours = MAX_DAILY_HOURS * calendar.monthrange(int(month[:4]), int(month[5:7]))[1]
            if hours is None or not 0.0 <= hours <= max_hours:
                raise ValueError(f"line {line}: heating_hours must be between 0 and {max_hours:g}")
            if source not in SOURCES:
                raise ValueError(f"line {line}: source must be one of report, prev, daily")
            out.append((month, hours, source))
    return out


def _beats(new_source: str, old_source: str) -> bool:
    """A report beats prev and daily; otherwise the first value stands."""
    return new_source == SOURCE_REPORT and old_source != SOURCE_REPORT


async def import_nest_months(
    sf: async_sessionmaker, rows: list[tuple[str, float, str]]
) -> tuple[int, int]:
    """Upsert monthly rows. Returns ``(imported, skipped_duplicates)``.

    Within one import, and against stored rows, a ``report`` value always
    beats ``prev`` or ``daily``. Among duplicates where neither side is a
    better source, the first row in the file (or the stored row against a
    non-report import) wins and the loser counts as skipped. A stored
    non-report row is replaced by any imported value (the import is
    authoritative over the daily roll-up and earlier back-fills).
    """
    chosen: dict[str, tuple[float, str]] = {}
    skipped = 0
    for month, hours, source in rows:
        current = chosen.get(month)
        if current is None:
            chosen[month] = (hours, source)
            continue
        skipped += 1
        if _beats(source, current[1]):
            chosen[month] = (hours, source)

    imported = 0
    async with sf() as session:
        for month, (hours, source) in chosen.items():
            existing = await session.get(NestHeatingMonthly, month)
            if existing is None:
                session.add(NestHeatingMonthly(month=month, heating_hours=hours, source=source))
            elif existing.source == SOURCE_REPORT and source != SOURCE_REPORT:
                skipped += 1
                continue
            else:
                existing.heating_hours = hours
                existing.source = source
            imported += 1
        await session.commit()
    return imported, skipped


async def load_nest_monthly(sf: async_sessionmaker) -> dict[str, float]:
    """``{"YYYY-MM": heating_hours}`` for every stored month."""
    async with sf() as session:
        rows = (await session.execute(select(NestHeatingMonthly))).scalars().all()
    return {r.month: float(r.heating_hours) for r in rows}


async def load_nest_daily(sf: async_sessionmaker, since: str) -> dict[str, float]:
    """``{"YYYY-MM-DD": heating_hours}`` for daily rows on or after ``since``."""
    async with sf() as session:
        rows = (
            await session.execute(select(NestHeatingDaily).where(NestHeatingDaily.date >= since))
        ).scalars().all()
    return {r.date: float(r.heating_hours) for r in rows}
