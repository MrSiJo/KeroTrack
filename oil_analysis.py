#!/usr/bin/env python3

"""
README:
This script analyzes domestic heating oil tank data stored in a SQLite database.
It calculates consumption rates, estimates days until empty, and computes CO2 emissions.
The script also publishes the analysis results to an MQTT topic for integration with
other home automation systems or dashboards.

Key features:
- Reads data from a SQLite database
- Performs temperature compensation on oil volume
- Calculates smoothed consumption rates
- Estimates remaining days of oil supply
- Computes CO2 emissions
- Publishes results to MQTT
- Logs analysis process and results

Usage:
Run this script periodically (e.g., daily) to keep analysis up-to-date.
Ensure the config.yaml file is properly set up with correct parameters.
"""

import sqlite3
from datetime import datetime, timedelta
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from db_connection import get_db_connection
import paho.mqtt.client as mqtt
import time
import calendar
import pandas as pd
import numpy as np
import sys
from utils.config_loader import load_config, get_config_value

# Load configuration
config = load_config()

# Setup logging
log_directory = get_config_value(config, 'logging', 'directory', default="logs")
os.makedirs(log_directory, exist_ok=True)
log_file = os.path.join(log_directory, f"{os.path.splitext(os.path.basename(__file__))[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# Set up the logger
logger = logging.getLogger(__name__)
logger.setLevel(get_config_value(config, 'logging', 'level', default="INFO"))

# Remove any existing handlers from both this logger and the root logger
logger.handlers = []
logging.getLogger().handlers = []

# Prevent propagation to root logger
logger.propagate = False

# Create handlers
file_handler = TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=get_config_value(config, 'logging', 'retention_days', default=7))
stream_handler = logging.StreamHandler()

# Create formatters and add it to handlers
log_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(log_format)
stream_handler.setFormatter(log_format)

# Add handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# Load constants from config
CO2_PER_LITER = get_config_value(config, 'analysis', 'co2_per_liter')
FUEL_RATE = get_config_value(config, 'boiler', 'fuel_rate')
OUTPUT_KW = get_config_value(config, 'boiler', 'output_kw')
EFFICIENCY = get_config_value(config, 'boiler', 'efficiency')
REFERENCE_TEMP = get_config_value(config, 'analysis', 'reference_temperature')
EXPANSION_COEFFICIENT = get_config_value(config, 'analysis', 'thermal_expansion_coefficient')
EMA_ALPHA = get_config_value(config, 'analysis', 'ema_alpha')
REFILL_THRESHOLD = get_config_value(config, 'detection', 'refill_threshold')
LEAK_THRESHOLD = get_config_value(config, 'detection', 'leak_threshold')
LEAK_DETECTION_PERIOD_DAYS = get_config_value(config, 'detection', 'leak_detection_period_days')

# MQTT configuration
MQTT_BROKER = get_config_value(config, 'mqtt', 'broker')
MQTT_PORT = get_config_value(config, 'mqtt', 'port')
MQTT_USERNAME = get_config_value(config, 'mqtt', 'username')
MQTT_PASSWORD = get_config_value(config, 'mqtt', 'password')

def get_topic_by_name(topics, logical_name):
    return next(topic['topicname'] for topic in topics if topic['name'] == logical_name)

topics = get_config_value(config, 'mqtt', 'topics')
MQTT_TOPIC = get_topic_by_name(topics, "KTanalytics")

# Database configuration
DB_PATH = get_config_value(config, 'database', 'path', default=os.path.join('data', 'oil_data.db'))

MINIMUM_CONSUMPTION_RATE = 0.01  # Liters per day

def get_table_columns(conn, table_name):
    c = conn.cursor()
    c.execute(f"PRAGMA table_info({table_name})")
    return [column[1] for column in c.fetchall()]

def get_latest_reading(conn):
    """Retrieve the most recent reading from the database."""
    c = conn.cursor()
    columns = get_table_columns(conn, 'readings')
    c.execute(f'SELECT {", ".join(columns)} FROM readings ORDER BY date DESC LIMIT 1')
    result = c.fetchone()
    return dict(zip(columns, result)) if result else None

def get_reading_days_ago(days, conn):
    """Retrieve a reading from a specified number of days ago."""
    c = conn.cursor()
    columns = get_table_columns(conn, 'readings')
    date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    c.execute(f'SELECT {", ".join(columns)} FROM readings WHERE date <= ? ORDER BY date DESC LIMIT 1', (date,))
    result = c.fetchone()
    return dict(zip(columns, result)) if result else None

def get_readings_last_n_days(conn, days):
    """Retrieve all readings from the last n days."""
    c = conn.cursor()
    columns = get_table_columns(conn, 'readings')
    date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    c.execute(f'SELECT {", ".join(columns)} FROM readings WHERE date >= ? ORDER BY date', (date,))
    results = c.fetchall()
    return [dict(zip(columns, row)) for row in results]

def temperature_compensated_volume(volume, temperature):
    """Calculate temperature-compensated oil volume."""
    return volume / (1 + EXPANSION_COEFFICIENT * (temperature - REFERENCE_TEMP))

def calculate_smoothed_consumption_rate(readings):
    """Calculate a smoothed daily consumption rate using exponential moving average."""
    if len(readings) < 2:
        logger.warning("Not enough readings to calculate consumption rate")
        return 0
    
    comp_volumes = [temperature_compensated_volume(r['litres_remaining'], r['temperature']) for r in readings]
    daily_rates = []
    for i in range(1, len(readings)):
        date1 = datetime.strptime(readings[i-1]['date'], '%Y-%m-%d %H:%M:%S')
        date2 = datetime.strptime(readings[i]['date'], '%Y-%m-%d %H:%M:%S')
        days = (date2 - date1).total_seconds() / 86400
        volume_diff = comp_volumes[i-1] - comp_volumes[i]
        
        logger.debug(f"Date1: {date1}, Date2: {date2}, Days: {days}, Volume diff: {volume_diff}")
        
        if days > 0:
            if volume_diff > 0:
                rate = volume_diff / days
                daily_rates.append(rate)
            elif volume_diff < -REFILL_THRESHOLD:
                logger.info(f"Detected refill: volume increased by {abs(volume_diff)} liters")
                daily_rates = []
            else:
                logger.warning(f"Skipped calculation: Days={days}, Volume diff={volume_diff}")
        else:
            logger.warning(f"Skipped calculation: Days={days}, Volume diff={volume_diff}")
    
    logger.info(f"Number of daily rates calculated: {len(daily_rates)}")
    logger.info(f"Daily rates: {daily_rates}")
    
    if not daily_rates:
        logger.warning("No valid daily rates calculated")
        return 0
    ema = daily_rates[0]
    for rate in daily_rates[1:]:
        ema = EMA_ALPHA * rate + (1 - EMA_ALPHA) * ema
    
    logger.info(f"Final smoothed consumption rate: {ema}")
    
    return max(ema, MINIMUM_CONSUMPTION_RATE)

def get_last_refill_reading(conn):
    """Retrieve the most recent refill reading from the database."""
    c = conn.cursor()
    columns = get_table_columns(conn, 'readings')
    c.execute(f"SELECT {', '.join(columns)} FROM readings WHERE refill_detected = 'y' ORDER BY date DESC LIMIT 1")
    result = c.fetchone()
    if result:
        logger.info(f"Last refill found: {dict(zip(columns, result))}")
        return dict(zip(columns, result))
    else:
        logger.warning("No refill detected in the database")
        return None

def check_recent_readings(conn):
    """Log the 10 most recent readings for debugging purposes."""
    c = conn.cursor()
    c.execute('SELECT date, refill_detected, leak_detected FROM readings ORDER BY date DESC LIMIT 10')
    results = c.fetchall()
    logger.info("Recent readings:")
    for row in results:
        logger.info(f"Date: {row[0]}, Refill Detected: {row[1]}, Leak Detected: {row[2]}")

def get_hdd_data(conn, start_date, end_date):
    """Retrieve HDD data for a given date range."""
    c = conn.cursor()
    c.execute('''SELECT date, hdd FROM hdd_data
                WHERE date BETWEEN ? AND ?
                ORDER BY date''', (start_date, end_date))
    return dict(c.fetchall())

def get_seasonal_heating_factor(month):
    """
    Return a heating factor based on historical Nest data.
    This factor represents the proportion of maximum heating usage for each month.
    """
    heating_hours = {
        1: 78,  # January
        2: 43,  # February
        3: 43,  # March
        4: 21,  # April
        5: 3,   # May
        6: 0,   # June
        7: 0,   # July
        8: 0,   # August
        9: 0,   # September
        10: 5,  # October
        11: 29, # November
        12: 37  # December
    }
    max_hours = max(heating_hours.values())
    return heating_hours[month] / max_hours if max_hours > 0 else 0

def get_readings_for_period(conn, start_date, end_date):
    """Retrieve readings for a specific date range."""
    c = conn.cursor()
    columns = get_table_columns(conn, 'readings')
    c.execute(f'SELECT {", ".join(columns)} FROM readings WHERE date BETWEEN ? AND ? ORDER BY date', (start_date, end_date))
    results = c.fetchall()
    return [dict(zip(columns, row)) for row in results]

def detect_leak(conn, current_reading):
    """Check if a leak has been detected in the current reading."""
    return current_reading.get('leak_detected', 'n')

def get_historical_consumption(conn):
    """Calculate historical average daily consumption from previous refill cycles.
    Only considers significant refills where volume increased by more than REFILL_THRESHOLD."""
    c = conn.cursor()
    c.execute('''
        WITH consecutive_readings AS (
            SELECT 
                date,
                litres_remaining,
                LAG(date) OVER (ORDER BY date) as prev_date,
                LAG(litres_remaining) OVER (ORDER BY date) as prev_litres,
                litres_remaining - LAG(litres_remaining) OVER (ORDER BY date) as volume_change
            FROM readings 
            WHERE refill_detected = 'y'
            ORDER BY date DESC
        ),
        significant_refills AS (
            SELECT 
                date,
                litres_remaining,
                prev_date,
                prev_litres,
                volume_change
            FROM consecutive_readings
            WHERE volume_change >= ?  -- Only consider significant refills
            LIMIT 5
        )
        SELECT 
            AVG((prev_litres - litres_remaining) / 
                (JULIANDAY(date) - JULIANDAY(prev_date))) as avg_daily
        FROM significant_refills
        WHERE prev_date IS NOT NULL
    ''')
    result = c.fetchone()[0]
    logger.info(f"Historical consumption calculation based on significant refills (>={REFILL_THRESHOLD}L)")
    return result if result is not None else 0

def get_smoothed_daily_usage(conn, days=7, refill_threshold=100):
    readings = get_readings_last_n_days(conn, days+1)  # Need N+1 readings for N days
    if len(readings) < 2:
        return None
    daily_usages = []
    for i in range(1, len(readings)):
        prev = readings[i-1]
        curr = readings[i]
        used = prev['litres_remaining'] - curr['litres_remaining']
        # Ignore refill days (large positive jumps)
        if used < -refill_threshold:
            continue
        # Ignore negative usage (shouldn't happen except for refills)
        if used < 0:
            continue
        daily_usages.append(used)
    if not daily_usages:
        return None
    return sum(daily_usages) / len(daily_usages)

def analyze_data(conn):
    """Main analysis function with both original and HDD-based calculations."""
    latest = get_latest_reading(conn)
    last_refill = get_last_refill_reading(conn)
    
    if latest and last_refill:
        result = {
            "latest_analysis_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        # Calculate consumption since last refill
        refill_date = datetime.strptime(last_refill['date'], '%Y-%m-%d %H:%M:%S')
        days_since_refill = (datetime.now() - refill_date).days
        total_consumption = last_refill['litres_remaining'] - latest['litres_remaining']
        
        # Calculate smoothed daily usage (ignoring refill days)
        smoothed_daily_usage = get_smoothed_daily_usage(conn, days=30, refill_threshold=REFILL_THRESHOLD)
        
        # Calculate average daily consumption since last refill (for reference)
        if days_since_refill > 0 and total_consumption > 0:
            avg_daily_consumption = total_consumption / days_since_refill
        else:
            avg_daily_consumption = get_historical_consumption(conn)
            if avg_daily_consumption > 0:
                logger.info(f"Using historical average consumption: {avg_daily_consumption:.2f} L/day")
            else:
                logger.warning("No significant historical refill cycles found for consumption calculation")
        
        # Use smoothed daily usage for projection if available
        if smoothed_daily_usage and smoothed_daily_usage > 0:
            days_until_empty = latest['litres_remaining'] / smoothed_daily_usage
            empty_date = datetime.now() + timedelta(days=days_until_empty)
        else:
            days_until_empty = float('inf')
            empty_date = None
        
        # HDD-based calculations
        start_date = refill_date.strftime('%Y-%m-01')
        end_date = datetime.now().strftime('%Y-%m-01')
        hdd_data = get_hdd_data(conn, start_date, end_date)
        
        total_hdd = sum(hdd_data.values())
        consumption_per_hdd = total_consumption / total_hdd if total_hdd > 0 else 0
        
        # Calculate the average HDD for the upcoming month
        current_month = datetime.now().month
        next_month = current_month + 1 if current_month < 12 else 1
        upcoming_hdd = hdd_data.get(datetime(datetime.now().year, next_month, 1).strftime('%Y-%m-01'), 0)
        
        # Estimate base consumption for scheduled hot water
        weekday_hot_water_sessions = 1 * 4  # 1 session per day, 4 weekdays
        weekend_hot_water_sessions = 2 * 3  # 2 sessions per day, 3 weekend days
        total_weekly_hot_water_sessions = weekday_hot_water_sessions + weekend_hot_water_sessions
        hot_water_heating_time = 0.5  # 30 minutes per session
        
        # Use the fuel_rate from config for hot water heating
        hot_water_fuel_rate = FUEL_RATE  # Liters per hour
        scheduled_daily_hot_water_consumption = (total_weekly_hot_water_sessions * hot_water_heating_time * hot_water_fuel_rate) / 7
        
        # Add a small buffer for potential ad hoc water heating (e.g., 10% extra)
        buffer_factor = 1.1
        estimated_daily_hot_water_consumption = scheduled_daily_hot_water_consumption * buffer_factor
        
        # Estimate daily heating consumption based on upcoming HDD and seasonal factor
        seasonal_factor = get_seasonal_heating_factor(next_month)
        heating_consumption = consumption_per_hdd * upcoming_hdd * seasonal_factor / calendar.monthrange(datetime.now().year, next_month)[1]
        
        estimated_daily_consumption_hdd = heating_consumption + estimated_daily_hot_water_consumption

        # HDD-based projection
        if estimated_daily_consumption_hdd > 0:
            days_until_empty_hdd = latest['litres_remaining'] / estimated_daily_consumption_hdd
            empty_date_hdd = datetime.now() + timedelta(days=days_until_empty_hdd)
        else:
            days_until_empty_hdd = float('inf')
            empty_date_hdd = None
        
        result.update({
            "days_since_refill": days_since_refill,
            "total_consumption_since_refill": round(total_consumption, 2),
            "avg_daily_consumption_l": round(avg_daily_consumption, 2),
            "estimated_days_remaining": round(days_until_empty, 1) if days_until_empty != float('inf') else "Unknown",
            "estimated_empty_date": empty_date.strftime('%d/%m/%Y') if empty_date else "Unknown",
            "consumption_per_hdd_l": round(consumption_per_hdd, 3),
            "upcoming_month_hdd": round(upcoming_hdd, 1),
            "estimated_daily_consumption_hdd_l": round(estimated_daily_consumption_hdd, 2),
            "estimated_daily_hot_water_consumption_l": round(estimated_daily_hot_water_consumption, 2),
            "estimated_daily_heating_consumption_l": round(heating_consumption, 2),
            "seasonal_heating_factor": round(seasonal_factor, 2),
            "remaining_days_empty_hdd": round(days_until_empty_hdd, 1) if days_until_empty_hdd != float('inf') else "Unknown",
            "remaining_date_empty_hdd": empty_date_hdd.strftime('%d/%m/%Y') if empty_date_hdd else "Unknown",
        })
        
        # Check if all expected keys are present
        expected_keys = {
            "latest_analysis_date", "days_since_refill", "total_consumption_since_refill", "avg_daily_consumption_l",
            "estimated_days_remaining", "estimated_empty_date", "consumption_per_hdd_l",
            "upcoming_month_hdd", "estimated_daily_consumption_hdd_l",
            "estimated_daily_hot_water_consumption_l", "estimated_daily_heating_consumption_l",
            "seasonal_heating_factor", "remaining_days_empty_hdd", "remaining_date_empty_hdd"
        }
        missing_keys = expected_keys - set(result.keys())
        if missing_keys:
            logger.warning(f"The following expected keys are missing from the analysis result: {missing_keys}")

        logger.info(f"Analysis result: {result}")
        return result
    else:
        logger.warning("Insufficient data for analysis (missing latest reading or last refill)")
        return None

def save_result_to_db(conn, result):
    """Save the analysis result to the database."""
    c = conn.cursor()
    
    columns = get_table_columns(conn, 'analysis_results')
    
    # Filter the result dictionary to only include keys that exist as columns
    filtered_result = {k: v for k, v in result.items() if k in columns}
    
    # Create the column names and placeholders for the existing columns
    column_names = ', '.join(filtered_result.keys())
    placeholders = ', '.join(['?' for _ in filtered_result])
    
    # Create a list of values in the same order as the column names
    values = [filtered_result[col] for col in filtered_result.keys()]

    query = f'''
    INSERT OR REPLACE INTO analysis_results 
    ({column_names})
    VALUES ({placeholders})
    '''
    
    c.execute(query, values)
    conn.commit()
    logger.info(f"Analysis result saved to database for date: {result.get('latest_analysis_date', '')}")
    
    # Log any keys in result that weren't in the database columns
    unused_keys = set(result.keys()) - set(columns)
    if unused_keys:
        logger.warning(f"The following keys were not saved to the database: {unused_keys}")

def on_connect(client, userdata, flags, rc):
    """Callback function for when the client receives a CONNACK response from the server."""
    if rc == 0:
        logger.info(f"Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
    else:
        logger.error(f"Failed to connect to MQTT broker with code {rc}")

def on_publish(client, userdata, mid):
    """Callback function for when a message is published."""
    logger.info(f"Message {mid} published successfully")

def publish_to_mqtt(result):
    """Publish the analysis result to the MQTT broker."""
    try:
        client = mqtt.Client()
        client.on_connect = on_connect
        client.on_publish = on_publish

        if MQTT_USERNAME and MQTT_PASSWORD:
            client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

        logger.info(f"Attempting to connect to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()

        start_time = time.time()
        while not client.is_connected() and time.time() - start_time < 10:
            time.sleep(0.1)

        if not client.is_connected():
            logger.error("Failed to connect to MQTT broker within timeout")
            client.loop_stop()
            return

        payload = json.dumps(result)
        
        logger.info(f"Attempting to publish to MQTT topic: {MQTT_TOPIC}")
        logger.debug(f"Payload: {payload}")
        
        publish_result = client.publish(MQTT_TOPIC, payload, qos=1, retain=True)  # Added retain=True
        
        start_time = time.time()
        while not publish_result.is_published() and time.time() - start_time < 10:
            time.sleep(0.1)

        if publish_result.is_published():
            logger.info(f"Message published successfully with retain flag. Message ID: {publish_result.mid}")
        else:
            logger.error(f"Failed to publish message within timeout. Result code: {publish_result.rc}")
        
        client.loop_stop()
        client.disconnect()
        logger.info("Disconnected from MQTT broker")
        
    except Exception as e:
        logger.error(f"Failed to publish to MQTT: {e}")
        logger.exception("Exception details:")

def check_database_format(conn):
    """Check if the database has the correct schema."""
    c = conn.cursor()
    c.execute("PRAGMA table_info(readings)")
    columns = {column[1]: column[2] for column in c.fetchall()}
    expected_columns = {
        'id': 'TEXT',
        'temperature': 'REAL',
        'litres_remaining': 'REAL',
        'litres_used_since_last': 'REAL',
        'percentage_remaining': 'REAL',
        'oil_depth_cm': 'REAL',
        'air_gap_cm': 'REAL',
        'current_ppl': 'REAL',
        'cost_used': 'TEXT',
        'cost_to_fill': 'TEXT',
        'heating_degree_days': 'REAL',
        'seasonal_efficiency': 'REAL',
        'refill_detected': 'TEXT',
        'leak_detected': 'TEXT',
        'raw_flags': 'TEXT',
        'litres_to_order': 'REAL',
        'bars_remaining': 'INTEGER'
    }
    for col, type_ in expected_columns.items():
        if col not in columns:
            logger.error(f"Database column '{col}' is missing")
            return False
        if columns[col] != type_:
            logger.error(f"Database column '{col}' is not in the correct format. Expected {type_}, got {columns[col]}")
            return False
    return True

if __name__ == '__main__':
    result = None
    with get_db_connection(DB_PATH) as conn:
        if check_database_format(conn):
            result = analyze_data(conn)
            if result:
                save_result_to_db(conn, result)
                publish_to_mqtt(result)
            else:
                logger.warning("Analysis could not be completed due to insufficient data.")
        else:
            logger.error("Exiting due to incorrect database format.")
    
    if result:
        logger.info(f"Analysis completed: {result}")
    else:
        logger.info("Analysis not completed due to errors or insufficient data.")

    time.sleep(5)