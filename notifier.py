#!/usr/bin/env python3

"""
Send weekly (and first-Sunday monthly) summaries for KeroTrack via Apprise.
Refill-aware calculations keep usage totals honest even when the tank is topped up.
"""

import sqlite3
from datetime import datetime, timedelta
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import sys
import apprise

# Add utils to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'utils'))

from db_connection import get_db_connection
from config_loader import load_config, get_config_value


def setup_logging(config):
    """Set up logging for the notifier script."""
    log_directory = get_config_value(config, 'logging', 'directory', default="logs")
    os.makedirs(log_directory, exist_ok=True)
    log_file = os.path.join(log_directory, f"{os.path.splitext(os.path.basename(__file__))[0]}.log")
    
    logger = logging.getLogger(__name__)
    logger.setLevel(get_config_value(config, 'logging', 'level', default="INFO"))

    logger.handlers = []
    logging.getLogger().handlers = []
    logger.propagate = False

    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=get_config_value(config, 'logging', 'retention_days', default=7),
    )
    stream_handler = logging.StreamHandler()

    log_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(log_format)
    stream_handler.setFormatter(log_format)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    
    return logger


def fetch_readings_between(conn, start_date, end_date):
    """Fetch readings between two datetimes (inclusive) ordered by date."""
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT date, litres_remaining, current_ppl, refill_detected, percentage_remaining
            FROM readings
            WHERE date BETWEEN ? AND ?
            ORDER BY date ASC
            """,
            (start_date, end_date),
        )
        rows = c.fetchall()
        return [
            {
                "date": row[0],
                "litres_remaining": row[1],
                "current_ppl": row[2],
                "refill_detected": row[3],
                "percentage_remaining": row[4],
            }
            for row in rows
        ]
    except sqlite3.Error as e:
        logging.getLogger(__name__).error(f"Database error when fetching readings: {e}")
        return []


def calculate_refill_aware_usage(readings, refill_threshold):
    """
    Calculate usage for a period while being aware of refills.
    Returns usage litres, refill flag/volume, and average ppl.
    """
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
        delta = curr["litres_remaining"] - prev["litres_remaining"]

        # Positive jump signals refill
        if (curr["refill_detected"] == "y") or (delta >= refill_threshold):
            had_refill = True
            refill_volume += delta if delta > 0 else 0.0
            continue

        decrease = prev["litres_remaining"] - curr["litres_remaining"]
        if decrease > 0:
            total_decrease += decrease

    start_litres = readings[0]["litres_remaining"]
    end_litres = readings[-1]["litres_remaining"]
    usage_without_refill = start_litres - end_litres
    usage_litres = total_decrease if had_refill else usage_without_refill
    usage_litres = max(usage_litres, 0.0)

    ppl_values = [r["current_ppl"] for r in readings if r["current_ppl"] is not None]
    average_ppl = (sum(ppl_values) / len(ppl_values)) if ppl_values else 0.0

    return {
        "usage_litres": usage_litres,
        "had_refill": had_refill,
        "refill_volume": refill_volume,
        "average_ppl": average_ppl,
    }


def format_diff(current, previous, precision=2, threshold=0.1, suffix=""):
    """Return a signed diff string or None if no data/change."""
    if current is None or previous is None:
        return None
    diff = current - previous
    if abs(diff) < threshold:
        return "No change"
    sign = "+" if diff > 0 else ""
    return f"{sign}{diff:.{precision}f}{suffix}"


def format_currency_diff(current, previous, currency_symbol):
    """Format a currency diff with the sign before the symbol."""
    diff_str = format_diff(current, previous)
    if not diff_str or diff_str == "No change":
        return diff_str
    sign = ""
    value = diff_str
    if diff_str.startswith(("+", "-")):
        sign, value = diff_str[0], diff_str[1:]
    return f"{sign}{currency_symbol}{value}"


def get_monthly_summary(conn, logger, config):
    """Calculate the summary for the previous full calendar month."""
    logger.info("Calculating last month's summary...")
    today = datetime.now()
    last_day_of_prev_month = today.replace(day=1) - timedelta(days=1)
    first_day_of_prev_month = last_day_of_prev_month.replace(day=1)
    
    start_date = first_day_of_prev_month.strftime('%Y-%m-%d 00:00:00')
    end_date = last_day_of_prev_month.strftime('%Y-%m-%d 23:59:59')
    month_name = last_day_of_prev_month.strftime("%B")
    
    logger.info(f"Calculating summary for {month_name} ({start_date} to {end_date})")

    try:
        readings = fetch_readings_between(conn, start_date, end_date)

        if len(readings) < 2:
            logger.warning("Not enough data to generate monthly summary.")
            return None

        refill_threshold = get_config_value(config, 'detection', 'refill_threshold', default=50)
        usage_stats = calculate_refill_aware_usage(readings, refill_threshold)
        start_litres = readings[0]["litres_remaining"]
        end_litres = readings[-1]["litres_remaining"]
        total_refill_volume = usage_stats["refill_volume"]
        total_usage = (start_litres - end_litres) + total_refill_volume

        if total_usage < 0:
            logger.warning(f"Calculated negative usage ({total_usage:.2f}L), clamping to 0.")
            total_usage = 0

        avg_ppl = usage_stats["average_ppl"]
        total_cost = (total_usage * avg_ppl) / 100
        
        tank_capacity = get_config_value(config, 'tank', 'capacity')
        percentage_used = (total_usage / tank_capacity) * 100 if tank_capacity > 0 else 0

        return {
            "month_name": month_name,
            "total_usage": total_usage,
            "percentage_used": percentage_used,
            "approx_cost": total_cost,
            "refill_volume": total_refill_volume,
        }

    except sqlite3.Error as e:
        logger.error(f"Database error during monthly summary: {e}")
        return None


def get_weekly_stats(conn, logger, config):
    """Get refill-aware weekly stats and comparison with the prior week."""
    logger.info("Fetching refill-aware weekly stats and current tank level...")

    now = datetime.now()
    start_current_week = (now - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    end_current_week = now.strftime('%Y-%m-%d %H:%M:%S')

    start_prev_week = (now - timedelta(days=14)).strftime('%Y-%m-%d %H:%M:%S')
    end_prev_week = (now - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')

    refill_threshold = get_config_value(config, 'detection', 'refill_threshold', default=50)
    currency_symbol = get_config_value(config, 'currency', 'symbol', default='£')
    tank_capacity = get_config_value(config, 'tank', 'capacity', default=0)

    current_week_readings = fetch_readings_between(conn, start_current_week, end_current_week)
    prev_week_readings = fetch_readings_between(conn, start_prev_week, end_prev_week)

    current_usage_stats = calculate_refill_aware_usage(current_week_readings, refill_threshold)
    prev_usage_stats = calculate_refill_aware_usage(prev_week_readings, refill_threshold)

    weekly_usage = current_usage_stats["usage_litres"]
    current_avg_ppl = current_usage_stats["average_ppl"]
    weekly_cost = (weekly_usage * current_avg_ppl) / 100 if weekly_usage is not None else None
    weekly_pct_of_tank = (weekly_usage / tank_capacity) * 100 if tank_capacity and weekly_usage is not None else None

    prev_week_usage = prev_usage_stats["usage_litres"]
    prev_week_cost = (prev_week_usage * prev_usage_stats["average_ppl"]) / 100 if prev_week_usage is not None else None
    prev_week_pct = (prev_week_usage / tank_capacity) * 100 if tank_capacity and prev_week_usage is not None else None

    c = conn.cursor()
    latest_analysis = {}
    try:
        c.execute(
            """
            SELECT estimated_days_remaining, latest_analysis_date, avg_daily_consumption_l, estimated_empty_date
            FROM analysis_results
            ORDER BY latest_analysis_date DESC LIMIT 1
            """
        )
        analysis_result = c.fetchone()
        if analysis_result:
            latest_analysis = {
                'estimated_days_remaining': analysis_result[0],
                'analysis_date': analysis_result[1],
                'avg_daily_consumption_l': analysis_result[2],
                'estimated_empty_date': analysis_result[3]
            }
            logger.info(f"Latest analysis found from: {analysis_result[1]}")
    except sqlite3.Error as e:
        logger.error(f"Database error when fetching analysis results: {e}")

    current_litres = None
    current_percentage = None
    try:
        c.execute("SELECT litres_remaining, percentage_remaining FROM readings ORDER BY date DESC LIMIT 1")
        current_level = c.fetchone()
        if current_level:
            current_litres = round(current_level[0], 2)
            current_percentage = round(current_level[1], 2)
            logger.info(f"Current tank level: {current_litres}L ({current_percentage}%)")
    except sqlite3.Error as e:
        logger.error(f"Database error when fetching current level: {e}")

    logger.info(
        f"Weekly usage: {weekly_usage if weekly_usage is not None else 'N/A'} L "
        f"(refill detected: {current_usage_stats['had_refill']}, "
        f"refill volume: {current_usage_stats['refill_volume']:.2f} L)"
    )

    return {
        'weekly_usage_l': weekly_usage,
        'weekly_cost': weekly_cost,
        'weekly_pct_of_tank': weekly_pct_of_tank,
        'weekly_refill': current_usage_stats['had_refill'],
        'weekly_refill_volume': current_usage_stats['refill_volume'],
        'prev_week_usage_l': prev_week_usage,
        'prev_week_cost': prev_week_cost,
        'prev_week_pct_of_tank': prev_week_pct,
        'latest_analysis': latest_analysis,
        'current_litres': current_litres,
        'current_percentage': current_percentage,
        'currency_symbol': currency_symbol,
    }


def send_notification(stats, config, logger, test_mode=False, monthly_stats=None):
    """
    Sends notification using Apprise.
    """
    apprise_urls = get_config_value(config, 'notifications', 'apprise_urls', default=[])
    if not apprise_urls:
        logger.error("Apprise URL(s) not configured in config.yaml under notifications.apprise_urls")
        return

    apobj = apprise.Apprise()
    for url in apprise_urls:
        if url.startswith("gotify://") and "format=markdown" not in url:
            separator = '&' if '?' in url else '?'
            modified_url = f"{url}{separator}format=markdown"
            logger.info(f"Modified Gotify URL for Markdown support: {modified_url}")
            apobj.add(modified_url)
        else:
            apobj.add(url)

    title = "KeroTrack Weekly Summary"
    
    currency_symbol = stats.get('currency_symbol', '£')
    weekly_usage = stats.get('weekly_usage_l')
    weekly_cost = stats.get('weekly_cost')
    weekly_pct = stats.get('weekly_pct_of_tank')

    current_litres = stats.get('current_litres')
    current_percentage = stats.get('current_percentage')
    
    latest_analysis = stats.get('latest_analysis', {})
    days_remaining = latest_analysis.get('estimated_days_remaining')
    if isinstance(days_remaining, (float, int)):
        days_remaining = int(round(days_remaining))

    empty_date = latest_analysis.get('estimated_empty_date', 'N/A')

    trend_litres = format_diff(weekly_usage, stats.get('prev_week_usage_l'))
    cost_trend = format_currency_diff(weekly_cost, stats.get('prev_week_cost'), currency_symbol)
    pct_trend = format_diff(stats.get('weekly_pct_of_tank'), stats.get('prev_week_pct_of_tank'), precision=1, threshold=0.05, suffix="%")

    trend_segments = [seg for seg in (trend_litres, cost_trend, pct_trend) if seg and seg != "No change"]
    trend_line = "No change" if not trend_segments else " / ".join(trend_segments) + " vs last week"

    weekly_refill_notice = ""
    if stats.get('weekly_refill') and stats.get('weekly_refill_volume', 0) > 0:
        weekly_refill_notice = f"\n🛢️ **Refill detected:** approx +{stats['weekly_refill_volume']:.2f} L added"

    weekly_usage_line = "N/A"
    if weekly_usage is not None:
        cost_str = f"~{currency_symbol}{weekly_cost:.2f}" if weekly_cost is not None else "N/A"
        pct_str = f"~{weekly_pct:.1f}% of tank" if weekly_pct is not None else "N/A"
        weekly_usage_line = f"{weekly_usage:.2f} L ({cost_str}, {pct_str})"

    tank_line = "N/A"
    if current_litres is not None and current_percentage is not None:
        tank_line = f"{current_litres} L ({current_percentage}%)"

    est_empty_line = f"{empty_date}"
    if days_remaining is not None:
        est_empty_line = f"{empty_date} ({days_remaining} days)"

    body = (
        f"⛽ **Tank Level:** {tank_line}\n"
        f"💧 **Weekly Usage:** {weekly_usage_line}{weekly_refill_notice}\n"
        f"📉 **Trend:** {trend_line}\n"
        f"🗓️ **Est. Empty:** {est_empty_line}"
    )

    if monthly_stats:
        month_cost = f"~{currency_symbol}{monthly_stats['approx_cost']:.2f}"
        month_pct = f"~{monthly_stats['percentage_used']:.1f}% of tank"
        refill_line = ""
        if monthly_stats.get("refill_volume", 0) > 0:
            refill_line = f"\n• Refills: +{monthly_stats['refill_volume']:.2f} L added this month"
        body += (
            f"\n\n---\n"
            f"📆 Last Month Summary ({monthly_stats['month_name']}):\n"
            f"• Total Usage: {monthly_stats['total_usage']:.2f} L ({month_pct})\n"
            f"• Approx. Cost: {month_cost}"
            f"{refill_line}"
        )

    if test_mode:
        title = f"[TEST] {title}"
        logger.info("Test mode enabled. Sending test notification.")

    if len(apobj.urls()) > 0:
        if not apobj.notify(body=body, title=title, body_format=apprise.NotifyFormat.MARKDOWN):
            logger.error("Failed to send notification.")
        else:
            logger.info("Notification sent successfully.")
    else:
        logger.warning("No valid Apprise URLs to notify.")


def main(test_mode=False):
    """Main function to generate and send notification."""
    config = load_config()
    logger = setup_logging(config)
    
    db_path = get_config_value(config, 'database', 'path', default=os.path.join('data', 'oil_data.db'))
    
    with get_db_connection(db_path) as conn:
        stats = get_weekly_stats(conn, logger, config)
        
        monthly_stats = None
        today = datetime.now()
        is_first_sunday = today.weekday() == 6 and 1 <= today.day <= 7

        if is_first_sunday or test_mode:
            logger.info("First Sunday of month or test mode detected. Generating monthly summary.")
            monthly_stats = get_monthly_summary(conn, logger, config)

        send_notification(stats, config, logger, test_mode, monthly_stats)


if __name__ == "__main__":
    is_test = '--test' in sys.argv
    main(test_mode=is_test)
