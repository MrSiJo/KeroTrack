"""Notifier — port of v1 `notifier.py` with the rich Markdown weekly + monthly format.

Predicate matches v1: weekly summary every Sunday, monthly summary appended on
the first Sunday of the month. Refill-aware totals are calculated identically.
Apprise URLs from settings; Gotify URLs are auto-tagged `format=markdown`.

A `test_mode=True` call always sends, regardless of the day-of-month
predicate, and includes the monthly block.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

import apprise
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from kerotrack.models.analysis_result import AnalysisResult
from kerotrack.models.reading import Reading, trusted_readings_clause
from kerotrack.settings.service import SettingsService

logger = logging.getLogger(__name__)


def is_weekly_run_day(now: datetime) -> bool:
    return now.weekday() == 6


def is_monthly_run_day(now: datetime) -> bool:
    return now.weekday() == 6 and now.day <= 7


@dataclass
class NotifierResult:
    sent: bool
    channels: int
    title: str
    body: str
    skipped_reason: str | None = None


# --------------------------------------------------------------- DB helpers


async def _fetch_readings_between(
    sf: async_sessionmaker, start: str, end: str
) -> list[dict[str, Any]]:
    """Window readings for the weekly digest.

    Excludes rows tagged ``noise_suppressed`` — the weekly "🛢️ Refill
    detected" notice fires off `delta >= refill_threshold`, which would
    otherwise fire every time a noise reading reverts to truth.
    """
    async with sf() as session:
        rows = (
            await session.execute(
                select(
                    Reading.date,
                    Reading.litres_remaining,
                    Reading.current_ppl,
                    Reading.refill_detected,
                    Reading.percentage_remaining,
                )
                .where(
                    Reading.date >= start,
                    Reading.date <= end,
                    trusted_readings_clause(),
                )
                .order_by(Reading.date.asc())
            )
        ).all()
    return [
        {
            "date": r.date,
            "litres_remaining": r.litres_remaining,
            "current_ppl": r.current_ppl,
            "refill_detected": r.refill_detected,
            "percentage_remaining": r.percentage_remaining,
        }
        for r in rows
    ]


async def _latest_reading(sf: async_sessionmaker) -> Reading | None:
    """Most recent TRUSTED reading — the digest's "⛽ Tank Level" line must
    not report a noise-suppressed multipath spike as the current level
    (this was the one site that had drifted and lacked the filter; KERO-H3)."""
    async with sf() as session:
        return (
            await session.execute(
                select(Reading)
                .where(trusted_readings_clause())
                .order_by(desc(Reading.date))
                .limit(1)
            )
        ).scalar_one_or_none()


async def _latest_analysis(sf: async_sessionmaker) -> AnalysisResult | None:
    async with sf() as session:
        return (
            await session.execute(
                select(AnalysisResult)
                .order_by(desc(AnalysisResult.latest_analysis_date))
                .limit(1)
            )
        ).scalar_one_or_none()


# --------------------------------------------------------------- maths


def _calculate_refill_aware_usage(
    readings: list[dict[str, Any]], refill_threshold: float
) -> dict[str, Any]:
    if len(readings) < 2:
        return {
            "usage_litres": None,
            "had_refill": False,
            "refill_volume": 0.0,
            "average_ppl": 0.0,
        }

    total_decrease = 0.0
    refill_volume = 0.0
    had_refill = False

    for i in range(1, len(readings)):
        prev = readings[i - 1]
        curr = readings[i]
        if prev["litres_remaining"] is None or curr["litres_remaining"] is None:
            continue
        delta = curr["litres_remaining"] - prev["litres_remaining"]
        if curr["refill_detected"] == "y" or delta >= refill_threshold:
            had_refill = True
            if delta > 0:
                refill_volume += delta
            continue
        decrease = prev["litres_remaining"] - curr["litres_remaining"]
        if decrease > 0:
            total_decrease += decrease

    start_litres = readings[0]["litres_remaining"] or 0.0
    end_litres = readings[-1]["litres_remaining"] or 0.0
    usage_without_refill = start_litres - end_litres
    usage_litres = total_decrease if had_refill else usage_without_refill
    usage_litres = max(usage_litres, 0.0)

    ppl_values = [r["current_ppl"] for r in readings if r["current_ppl"] is not None]
    average_ppl = sum(ppl_values) / len(ppl_values) if ppl_values else 0.0

    return {
        "usage_litres": usage_litres,
        "had_refill": had_refill,
        "refill_volume": refill_volume,
        "average_ppl": average_ppl,
    }


def _format_diff(
    current: float | None,
    previous: float | None,
    *,
    precision: int = 2,
    threshold: float = 0.1,
    suffix: str = "",
) -> str | None:
    if current is None or previous is None:
        return None
    diff = current - previous
    if abs(diff) < threshold:
        return "No change"
    return f"{abs(diff):.{precision}f}{suffix}"


def _format_currency_diff(
    current: float | None, previous: float | None, currency_symbol: str
) -> str | None:
    diff_str = _format_diff(current, previous)
    if not diff_str or diff_str == "No change":
        return diff_str
    return f"{currency_symbol}{diff_str}"


# --------------------------------------------------------------- weekly stats


async def _get_weekly_stats(
    sf: async_sessionmaker,
    svc: SettingsService,
    *,
    now: datetime,
) -> dict[str, Any]:
    refill_threshold = float(await svc.get("detection.refill_threshold_l"))
    currency_symbol = str(await svc.get("currency.symbol"))
    tank_capacity = float(await svc.get("tank.capacity_l"))

    fmt = "%Y-%m-%d %H:%M:%S"
    start_current = (now - timedelta(days=7)).strftime(fmt)
    end_current = now.strftime(fmt)
    start_prev = (now - timedelta(days=14)).strftime(fmt)
    end_prev = start_current

    current_readings = await _fetch_readings_between(sf, start_current, end_current)
    prev_readings = await _fetch_readings_between(sf, start_prev, end_prev)

    current_stats = _calculate_refill_aware_usage(current_readings, refill_threshold)
    prev_stats = _calculate_refill_aware_usage(prev_readings, refill_threshold)

    weekly_usage = current_stats["usage_litres"]
    weekly_cost = (
        (weekly_usage * current_stats["average_ppl"]) / 100
        if weekly_usage is not None
        else None
    )
    weekly_pct = (
        (weekly_usage / tank_capacity) * 100
        if tank_capacity and weekly_usage is not None
        else None
    )

    prev_usage = prev_stats["usage_litres"]
    prev_cost = (
        (prev_usage * prev_stats["average_ppl"]) / 100
        if prev_usage is not None
        else None
    )
    prev_pct = (
        (prev_usage / tank_capacity) * 100
        if tank_capacity and prev_usage is not None
        else None
    )

    latest_reading = await _latest_reading(sf)
    latest_analysis = await _latest_analysis(sf)

    return {
        "weekly_usage_l": weekly_usage,
        "weekly_cost": weekly_cost,
        "weekly_pct_of_tank": weekly_pct,
        "weekly_refill": current_stats["had_refill"],
        "weekly_refill_volume": current_stats["refill_volume"],
        "prev_week_usage_l": prev_usage,
        "prev_week_cost": prev_cost,
        "prev_week_pct_of_tank": prev_pct,
        "current_litres": (
            round(latest_reading.litres_remaining, 2)
            if latest_reading and latest_reading.litres_remaining is not None
            else None
        ),
        "current_percentage": (
            round(latest_reading.percentage_remaining, 2)
            if latest_reading and latest_reading.percentage_remaining is not None
            else None
        ),
        "estimated_days_remaining": (
            int(round(latest_analysis.estimated_days_remaining))
            if latest_analysis
            and latest_analysis.estimated_days_remaining is not None
            else None
        ),
        "estimated_empty_date": (
            latest_analysis.estimated_empty_date if latest_analysis else None
        ),
        "currency_symbol": currency_symbol,
    }


# --------------------------------------------------------------- monthly


async def _get_monthly_summary(
    sf: async_sessionmaker,
    svc: SettingsService,
    *,
    now: datetime,
) -> dict[str, Any] | None:
    last_day_prev = now.replace(day=1) - timedelta(days=1)
    first_day_prev = last_day_prev.replace(day=1)
    start = first_day_prev.strftime("%Y-%m-%d 00:00:00")
    end = last_day_prev.strftime("%Y-%m-%d 23:59:59")
    month_name = last_day_prev.strftime("%B")

    readings = await _fetch_readings_between(sf, start, end)
    if len(readings) < 2:
        return None

    refill_threshold = float(await svc.get("detection.refill_threshold_l"))
    tank_capacity = float(await svc.get("tank.capacity_l"))
    stats = _calculate_refill_aware_usage(readings, refill_threshold)
    start_l = readings[0]["litres_remaining"] or 0.0
    end_l = readings[-1]["litres_remaining"] or 0.0
    refill_vol = stats["refill_volume"]
    total_usage = max(0.0, (start_l - end_l) + refill_vol)
    avg_ppl = stats["average_ppl"]
    total_cost = (total_usage * avg_ppl) / 100
    pct_used = (total_usage / tank_capacity) * 100 if tank_capacity else 0.0

    return {
        "month_name": month_name,
        "total_usage": total_usage,
        "percentage_used": pct_used,
        "approx_cost": total_cost,
        "refill_volume": refill_vol,
    }


# --------------------------------------------------------------- body builder


def _build_body(
    stats: dict[str, Any], monthly_stats: dict[str, Any] | None
) -> tuple[str, str]:
    currency_symbol = stats["currency_symbol"]
    weekly_usage = stats["weekly_usage_l"]
    weekly_cost = stats["weekly_cost"]
    weekly_pct = stats["weekly_pct_of_tank"]
    current_litres = stats["current_litres"]
    current_percentage = stats["current_percentage"]
    days_remaining = stats["estimated_days_remaining"]
    empty_date = stats["estimated_empty_date"] or "N/A"

    trend_litres = _format_diff(weekly_usage, stats["prev_week_usage_l"])
    cost_trend = _format_currency_diff(
        weekly_cost, stats["prev_week_cost"], currency_symbol
    )
    pct_trend = _format_diff(
        weekly_pct,
        stats["prev_week_pct_of_tank"],
        precision=1,
        threshold=0.05,
        suffix="%",
    )

    direction = None
    if weekly_usage is not None and stats["prev_week_usage_l"] is not None:
        diff_val = weekly_usage - stats["prev_week_usage_l"]
        if abs(diff_val) < 0.1:
            direction = "flat"
        elif diff_val > 0:
            direction = "up"
        else:
            direction = "down"

    if direction in (None, "flat") or all(
        seg in (None, "No change") for seg in (trend_litres, cost_trend, pct_trend)
    ):
        trend_line = "➖ No meaningful change"
    else:
        arrow = "⬆️" if direction == "up" else "⬇️"
        sign = "+" if direction == "up" else "-"
        parts: list[str] = []
        if trend_litres and trend_litres != "No change":
            parts.append(f"{sign}{trend_litres} L")
        if cost_trend and cost_trend != "No change":
            parts.append(f"{sign}{cost_trend.lstrip('+-')}")
        if pct_trend and pct_trend != "No change":
            parts.append(f"{sign}{pct_trend}")
        trend_line = f"{arrow} " + " / ".join(parts) + " vs last week"

    refill_notice = ""
    if stats["weekly_refill"] and stats["weekly_refill_volume"] > 0:
        refill_notice = (
            f"🛢️ **Refill detected:** approx +{stats['weekly_refill_volume']:.2f} L added"
        )

    weekly_usage_line = "N/A"
    if weekly_usage is not None:
        cost_str = (
            f"~{currency_symbol}{weekly_cost:.2f}" if weekly_cost is not None else "N/A"
        )
        pct_str = f"~{weekly_pct:.1f}% of tank" if weekly_pct is not None else "N/A"
        weekly_usage_line = f"{weekly_usage:.2f} L ({cost_str}, {pct_str})"

    tank_line = "N/A"
    if current_litres is not None and current_percentage is not None:
        tank_line = f"{current_litres} L ({current_percentage}%)"

    est_empty_line = empty_date
    if days_remaining is not None:
        est_empty_line = f"{empty_date} ({days_remaining} days)"

    weekly_lines = [
        f"- ⛽ **Tank Level:** {tank_line}",
        f"- 💧 **Weekly Usage:** {weekly_usage_line}",
        f"- 📉 **Trend:** {trend_line}",
        f"- 🗓️ **Est. Empty:** {est_empty_line}",
    ]
    if refill_notice:
        weekly_lines.insert(2, f"- {refill_notice}")
    body = "\n".join(weekly_lines)

    if monthly_stats:
        month_cost = f"~{currency_symbol}{monthly_stats['approx_cost']:.2f}"
        month_pct = f"~{monthly_stats['percentage_used']:.1f}% of tank"
        monthly_lines = [
            f"📆 **Last Month Summary ({monthly_stats['month_name']}):**",
            f"- **Total Usage:** {monthly_stats['total_usage']:.2f} L ({month_pct})",
            f"- **Approx. Cost:** {month_cost}",
        ]
        if monthly_stats.get("refill_volume", 0) > 0:
            monthly_lines.insert(
                2,
                f"- **Refill:** +{monthly_stats['refill_volume']:.2f} L added this month",
            )
        body = body + "\n\n---\n" + "\n".join(monthly_lines)

    title = "KeroTrack Weekly Summary"
    return title, body


# --------------------------------------------------------------- main entry


def _build_apprise(urls: list[str]) -> apprise.Apprise:
    instance = apprise.Apprise()
    for url in urls:
        if url.startswith("gotify://") and "format=markdown" not in url:
            sep = "&" if "?" in url else "?"
            instance.add(f"{url}{sep}format=markdown")
        else:
            instance.add(url)
    return instance


async def run(
    *,
    sf: async_sessionmaker,
    settings_service: SettingsService,
    test_mode: bool = False,
    now: datetime | None = None,
    apprise_factory: Callable[[list[str]], Any] | None = None,
) -> NotifierResult:
    """Run the notifier predicate and dispatch a rich Markdown summary."""
    if now is None:
        from kerotrack.clock import local_now
        now = local_now().replace(tzinfo=None)
    weekly_enabled = bool(await settings_service.get("notifications.weekly_enabled"))
    monthly_enabled = bool(await settings_service.get("notifications.monthly_enabled"))

    if test_mode:
        is_weekly = True
        include_monthly = True
    else:
        is_weekly = weekly_enabled and is_weekly_run_day(now)
        include_monthly = (
            monthly_enabled and is_weekly and is_monthly_run_day(now)
        )

    urls = list(await settings_service.get("notifications.apprise_urls") or [])

    if not is_weekly:
        return NotifierResult(
            sent=False,
            channels=0,
            title="",
            body="",
            skipped_reason="not a scheduled run day",
        )

    if not urls:
        return NotifierResult(
            sent=False,
            channels=0,
            title="",
            body="",
            skipped_reason="no apprise URLs configured",
        )

    stats = await _get_weekly_stats(sf, settings_service, now=now)
    monthly_stats = (
        await _get_monthly_summary(sf, settings_service, now=now)
        if include_monthly
        else None
    )

    title, body = _build_body(stats, monthly_stats)
    if test_mode:
        title = f"[TEST] {title}"

    instance = (
        apprise_factory(urls) if apprise_factory else _build_apprise(urls)
    )
    # apprise.notify() is synchronous network I/O — a slow Gotify/SMTP
    # target would otherwise stall the whole event loop (SSE, MQTT ingest)
    # for the duration, so run it in a worker thread (KERO-M1).
    ok = bool(
        await asyncio.to_thread(
            instance.notify,
            body=body,
            title=title,
            body_format=apprise.NotifyFormat.MARKDOWN,
        )
    )
    return NotifierResult(
        sent=ok,
        channels=len(urls),
        title=title,
        body=body,
        skipped_reason=None,
    )
