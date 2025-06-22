#!/usr/bin/env python3

"""
This script sends weekly summary notifications for KeroTrack.
It connects to the database, calculates weekly statistics,
and sends a notification using Apprise.
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

    file_handler = TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=get_config_value(config, 'logging', 'retention_days', default=7))
    stream_handler = logging.StreamHandler()

    log_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(log_format)
    stream_handler.setFormatter(log_format)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    
    return logger

def get_monthly_summary(conn, logger, config):
    """Calculate the summary for the previous full calendar month."""
    logger.info("Calculating last month's summary...")
    today = datetime.now()
    # Go to the last day of the previous month
    last_day_of_prev_month = today.replace(day=1) - timedelta(days=1)
    # Go to the first day of that same month
    first_day_of_prev_month = last_day_of_prev_month.replace(day=1)
    
    start_date = first_day_of_prev_month.strftime('%Y-%m-%d 00:00:00')
    end_date = last_day_of_prev_month.strftime('%Y-%m-%d 23:59:59')
    month_name = last_day_of_prev_month.strftime("%B")
    
    logger.info(f"Calculating summary for {month_name} ({start_date} to {end_date})")

    c = conn.cursor()
    try:
        # Get all readings for the month to calculate refills and average PPL
        c.execute("SELECT litres_remaining, current_ppl FROM readings WHERE date BETWEEN ? AND ? ORDER BY date ASC", (start_date, end_date))
        readings = c.fetchall()

        if len(readings) < 2:
            logger.warning("Not enough data to generate monthly summary.")
            return None

        # Get start and end levels for the month
        start_litres = readings[0][0]
        end_litres = readings[-1][0]

        # Calculate total refills during the month
        total_refill_volume = 0
        refill_threshold = get_config_value(config, 'detection', 'refill_threshold', default=50)
        for i in range(1, len(readings)):
            prev_litres = readings[i-1][0]
            curr_litres = readings[i][0]
            volume_increase = curr_litres - prev_litres
            if volume_increase >= refill_threshold:
                logger.info(f"Detected monthly refill of {volume_increase:.2f}L")
                total_refill_volume += volume_increase

        # Correctly calculate usage: (start - end) + refills
        total_usage = (start_litres - end_litres) + total_refill_volume

        # If total_usage is negative, it indicates noise or small top-ups. Clamp to 0.
        if total_usage < 0:
            logger.warning(f"Calculated negative usage ({total_usage:.2f}L), clamping to 0.")
            total_usage = 0

        # Calculate cost using the average PPL for the month
        ppl_values = [r[1] for r in readings if r[1] is not None]
        avg_ppl = sum(ppl_values) / len(ppl_values) if ppl_values else 0
        total_cost = (total_usage * avg_ppl) / 100
        currency_symbol = get_config_value(config, 'currency', 'symbol', default='£')
        
        # Calculate percentage of tank used
        tank_capacity = get_config_value(config, 'tank', 'capacity')
        percentage_used = (total_usage / tank_capacity) * 100 if tank_capacity > 0 else 0

        return {
            "month_name": month_name,
            "total_usage": f"{total_usage:.2f} L",
            "percentage_used": f"~{percentage_used:.1f}% of tank",
            "approx_cost": f"~{currency_symbol}{total_cost:.2f}"
        }

    except sqlite3.Error as e:
        logger.error(f"Database error during monthly summary: {e}")
        return None

def get_weekly_stats(conn, logger, config):
    """
    Get stats for the last 7 days from the analysis results.
    """
    logger.info("Fetching latest analysis and current stats...")

    stats = {
        'litres_used_last_7_days': 'N/A',
        'latest_analysis': {}
    }
    c = conn.cursor()

    try:
        c.execute("SELECT estimated_days_remaining, latest_analysis_date, avg_daily_consumption_l, estimated_empty_date FROM analysis_results ORDER BY latest_analysis_date DESC LIMIT 1")
        analysis_result = c.fetchone()
        if analysis_result:
            avg_daily_consumption = analysis_result[2] if analysis_result[2] is not None else 0
            stats['litres_used_last_7_days'] = round(avg_daily_consumption * 7, 2)
            
            stats['latest_analysis'] = {
                'estimated_days_remaining': analysis_result[0],
                'analysis_date': analysis_result[1],
                'avg_daily_consumption_l': avg_daily_consumption,
                'estimated_empty_date': analysis_result[3]
            }
            logger.info(f"Latest analysis found from: {analysis_result[1]}")
            logger.info(f"Calculated weekly usage: {stats['litres_used_last_7_days']} L (based on {avg_daily_consumption} L/day)")

            # Fetch last week's analysis for trend calculation
            last_week_date = (datetime.strptime(analysis_result[1], '%Y-%m-%d %H:%M:%S') - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
            c.execute("SELECT avg_daily_consumption_l FROM analysis_results WHERE latest_analysis_date <= ? ORDER BY latest_analysis_date DESC LIMIT 1", (last_week_date,))
            last_week_analysis = c.fetchone()

            usage_trend = "N/A"
            usage_trend_icon = "➖"
            if last_week_analysis and last_week_analysis[0] is not None:
                current_weekly_usage = stats['litres_used_last_7_days']
                previous_weekly_usage = round(last_week_analysis[0] * 7, 2)
                diff = current_weekly_usage - previous_weekly_usage
                
                if diff > 0.1:
                    usage_trend_icon = "📈"
                    usage_trend = f"+{diff:.2f} L"
                elif diff < -0.1:
                    usage_trend_icon = "📉"
                    usage_trend = f"{diff:.2f} L"
                else:
                    usage_trend = "No change"
                logger.info(f"Usage trend: Current {current_weekly_usage}L, Previous {previous_weekly_usage}L, Diff {diff:.2f}L")
            
            stats['usage_trend_icon'] = usage_trend_icon
            stats['usage_trend'] = usage_trend

        else:
            logger.warning("No analysis results found to calculate weekly usage.")

    except sqlite3.Error as e:
        logger.error(f"Database error when fetching analysis results: {e}")

    # Fetch latest PPL for cost calculation
    try:
        c.execute("SELECT current_ppl FROM readings ORDER BY date DESC LIMIT 1")
        latest_ppl_res = c.fetchone()
        weekly_cost = ""
        if latest_ppl_res and latest_ppl_res[0] is not None:
            latest_ppl = latest_ppl_res[0]
            current_weekly_usage = stats.get('litres_used_last_7_days', 0)
            if isinstance(current_weekly_usage, (int, float)):
                cost = (current_weekly_usage * latest_ppl) / 100
                currency_symbol = get_config_value(config, 'currency', 'symbol', default='£')
                weekly_cost = f"~{currency_symbol}{cost:.2f}"
                logger.info(f"Calculated weekly cost: {weekly_cost} based on PPL of {latest_ppl}")
        stats['weekly_cost'] = weekly_cost
    except sqlite3.Error as e:
        logger.error(f"Database error when fetching PPL: {e}")

    try:
        c.execute("SELECT litres_remaining, percentage_remaining FROM readings ORDER BY date DESC LIMIT 1")
        current_level = c.fetchone()
        if current_level:
            stats['current_litres'] = round(current_level[0], 2)
            stats['current_percentage'] = round(current_level[1], 2)
            logger.info(f"Current tank level: {stats['current_litres']}L ({stats['current_percentage']}%)")
    except sqlite3.Error as e:
        logger.error(f"Database error when fetching current level: {e}")

    return stats

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
        # Automatically append format=markdown to Gotify URLs for proper rendering
        if url.startswith("gotify://") and "format=markdown" not in url:
            separator = '&' if '?' in url else '?'
            modified_url = f"{url}{separator}format=markdown"
            logger.info(f"Modified Gotify URL for Markdown support: {modified_url}")
            apobj.add(modified_url)
        else:
            apobj.add(url)

    title = "KeroTrack Weekly Summary"
    
    # Safely get all the stats, providing a default value if a key is missing
    weekly_usage = stats.get('litres_used_last_7_days', 'N/A')
    weekly_cost_str = f"({stats.get('weekly_cost')})" if stats.get('weekly_cost') else ""
    current_litres = stats.get('current_litres', 'N/A')
    current_percentage = stats.get('current_percentage', 'N/A')
    
    latest_analysis = stats.get('latest_analysis', {})
    days_remaining = latest_analysis.get('estimated_days_remaining', 'N/A')
    if isinstance(days_remaining, (float, int)):
        days_remaining = int(round(days_remaining))

    empty_date = latest_analysis.get('estimated_empty_date', 'N/A')
    
    usage_trend_icon = stats.get('usage_trend_icon', '➖')
    usage_trend = stats.get('usage_trend', 'N/A')
    
    if usage_trend in ['N/A', 'No change']:
        trend_line = f"- 📊 **Trend:** {usage_trend_icon} {usage_trend}"
    else:
        trend_line = f"- 📊 **Trend:** {usage_trend_icon} {usage_trend} vs last week"


    # Format as a markdown list for better readability.
    body = (
        f"- ⛽️ **Tank Level:** {current_litres} L ({current_percentage}%)\n"
        f"- 💧 **Weekly Usage:** {weekly_usage} L {weekly_cost_str}\n"
        f"{trend_line}\n"
        f"- 🗓️ **Est. Empty:** {empty_date} ({days_remaining} days remaining)"
    )

    # Append monthly summary if available
    if monthly_stats:
        body += (
            f"\n\n---\n"
            f"**Last Month's Summary ({monthly_stats['month_name']}):**\n"
            f"- **Total Usage:** {monthly_stats['total_usage']} ({monthly_stats['percentage_used']})\n"
            f"- **Approx. Cost:** {monthly_stats['approx_cost']}"
        )

    if test_mode:
        title = f"[TEST] {title}"
        logger.info("Test mode enabled. Sending test notification.")

    # Notify with Markdown format specified, only if there are URLs.
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