#!/usr/bin/env python3

"""
README:
This script analyzes the cost of domestic heating oil between refill events.
It calculates various cost metrics like total cost between refills, daily/weekly/monthly
averages, and other useful insights for budget planning and consumption monitoring.

Key features:
- Identifies all refill events in the database
- Calculates costs between consecutive refills
- Generates daily/weekly/monthly average cost metrics
- Provides historical cost trends and insights
- Publishes results to MQTT for dashboard integration
- Allows input of actual refill costs for more accurate analysis

Usage:
1. To run analysis: python oil_cost_analysis.py
2. To add actual refill data: python oil_cost_analysis.py --add-refill
3. To list saved refill data: python oil_cost_analysis.py --list-refills
4. To delete specific refill data: python oil_cost_analysis.py --delete-refill
5. To clear all refill data: python oil_cost_analysis.py --clear-refills
6. To import historical deliveries: python oil_cost_analysis.py --import-historical
7. To run analysis without publishing: python oil_cost_analysis.py --analyze
8. For help: python oil_cost_analysis.py --help

Command-line parameters:
--add-refill         Add actual refill cost data interactively
--list-refills       List all actual refill cost data in the database
--delete-refill      Delete a specific refill cost record
--clear-refills      Clear all refill cost records from the database
--import-historical  Import refill data from historical_deliveries.txt
--analyze            Run the cost analysis and publish results
--help               Show help message and exit

Notes:
- The script requires a config.yaml file with MQTT and database settings
- For historical imports, data should be in data/historical_deliveries.txt
- Format for historical_deliveries.txt:
  Product - Quantity - Service - Delivery By - ppl - Order Total
"""

import sqlite3
from datetime import datetime, timedelta
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import yaml
import os
from db_connection import get_db_connection
import paho.mqtt.client as mqtt
import time
import pandas as pd
import numpy as np
import calendar
import sys
import argparse

# Setup logging
try:
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'config.yaml')
    with open(config_path, 'r') as config_file:
        config = yaml.safe_load(config_file)
    
    # Logging configuration
    log_directory = config.get('logging', {}).get('directory', "logs")
    log_level = config.get('logging', {}).get('level', "INFO")
    log_retention_days = config.get('logging', {}).get('retention_days', 7)
    
    # Create logging directory if it doesn't exist
    os.makedirs(log_directory, exist_ok=True)
    log_file = os.path.join(log_directory, f"{os.path.splitext(os.path.basename(__file__))[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    
    # Set up the logger
    logger = logging.getLogger(__name__)
    
    # Set log level
    log_level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL
    }
    # Temporarily set to DEBUG for diagnosing issues
    logger.setLevel(logging.DEBUG)  # Change back to log_level_map.get(log_level, logging.INFO) after debugging
    
    # Remove any existing handlers
    logger.handlers = []
    logging.getLogger().handlers = []
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    # Create handlers
    file_handler = TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=log_retention_days)
    stream_handler = logging.StreamHandler()
    
    # Create formatters and add it to handlers
    log_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(log_format)
    stream_handler.setFormatter(log_format)
    
    # Add handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    
    # MQTT configuration
    MQTT_BROKER = config.get('mqtt', {}).get('broker')
    MQTT_PORT = config.get('mqtt', {}).get('port')
    MQTT_USERNAME = config.get('mqtt', {}).get('username')
    MQTT_PASSWORD = config.get('mqtt', {}).get('password')
    
    # Find cost analysis topic from the topics list
    MQTT_TOPIC = None
    for topic in config.get('mqtt', {}).get('topics', []):
        if topic.get('name') == "KTcostanalysis":
            MQTT_TOPIC = topic.get('topicname')
            break
    
    if not MQTT_TOPIC:
        raise SystemExit(f"Failed to find KTcostanalysis topic in configuration")
    
    # Database configuration
    DB_PATH = config.get('database', {}).get('path')
    
    # Other config values
    CURRENCY_SYMBOL = config.get('currency', {}).get('symbol', '£')
    
    # Energy conversion constants
    HEATING_OIL_KWH_PER_LITER = config.get('energy', {}).get('kwh_per_liter', 10.35)  # Default value: ~10.35 kWh per liter of heating oil
    
except Exception as e:
    logger.error(f"Error loading configuration: {e}")
    raise SystemExit(f"Failed to load configuration: {e}")

def setup_database(conn):
    """Create necessary tables if they don't exist."""
    c = conn.cursor()
    
    # Create the actual_refill_costs table if it doesn't exist
    c.execute('''
    CREATE TABLE IF NOT EXISTS actual_refill_costs (
        refill_date TEXT PRIMARY KEY,
        actual_volume_litres REAL,
        actual_ppl REAL,
        total_cost REAL,
        invoice_ref TEXT,
        notes TEXT,
        entry_date TEXT,
        order_date TEXT,
        order_ref TEXT
    )
    ''')
    
    # Create the cost_analysis table with individual columns for key metrics
    c.execute('''
    CREATE TABLE IF NOT EXISTS cost_analysis (
        analysis_date TEXT PRIMARY KEY,
        
        -- Latest period data
        latest_period_start TEXT,
        latest_period_end TEXT,
        latest_period_days INTEGER,
        latest_refill_amount REAL,
        latest_refill_cost REAL,
        latest_refill_ppl REAL,
        latest_total_consumption REAL,
        latest_total_cost REAL,
        latest_daily_cost REAL,
        latest_weekly_cost REAL,
        latest_monthly_cost REAL,
        days_since_refill INTEGER,
        
        -- Historical averages
        avg_period_cost REAL,
        avg_period_consumption REAL,
        avg_daily_cost REAL,
        avg_weekly_cost REAL,
        avg_monthly_cost REAL,
        avg_annual_cost REAL,
        
        -- Weather metrics
        avg_cost_per_hdd REAL,
        avg_consumption_per_hdd REAL,
        
        -- Energy metrics
        avg_cost_per_kwh REAL,
        avg_daily_energy_kwh REAL,
        
        -- Efficiency metrics
        avg_cost_per_heat_unit REAL,
        
        -- Stats
        total_refill_periods INTEGER,
        percentage_with_actual_data REAL,
        
        -- Complete JSON for backward compatibility
        analysis_data TEXT
    )
    ''')
    
    # Check if energy_efficiency column exists in cost_analysis table, add it if not
    c.execute("PRAGMA table_info(cost_analysis)")
    columns = [column[1] for column in c.fetchall()]
    if 'energy_efficiency' not in columns:
        logger.info("Adding energy_efficiency column to cost_analysis table")
        try:
            c.execute("ALTER TABLE cost_analysis ADD COLUMN energy_efficiency REAL")
        except Exception as e:
            logger.warning(f"Could not add energy_efficiency column: {e}")
    
    # Create the energy_metrics table if it doesn't exist
    c.execute('''
    CREATE TABLE IF NOT EXISTS energy_metrics (
        period_start TEXT,
        period_end TEXT,
        total_energy_kwh REAL,
        delivered_energy_kwh REAL,
        cost_per_kwh REAL,
        cost_per_useful_kwh REAL,
        daily_energy_kwh REAL,
        energy_efficiency REAL,  -- Stored as decimal (0-1)
        analysis_date TEXT,
        PRIMARY KEY (period_start, period_end)
    )
    ''')
    
    # Create a table for period data
    c.execute('''
    CREATE TABLE IF NOT EXISTS refill_periods (
        start_date TEXT,
        end_date TEXT,
        days INTEGER,
        total_consumption REAL,
        average_ppl REAL,
        total_cost REAL,
        daily_cost REAL,
        weekly_cost REAL,
        monthly_cost REAL,
        refill_amount_liters REAL,
        refill_ppl REAL,
        refill_cost REAL,
        refill_invoice TEXT,
        refill_notes TEXT,
        used_actual_cost INTEGER,
        analysis_date TEXT,
        
        -- Weather metrics
        total_hdd REAL,
        cost_per_hdd REAL,
        consumption_per_hdd REAL,
        
        -- Energy metrics stored in separate table
        
        PRIMARY KEY (start_date, end_date)
    )
    ''')
    
    conn.commit()
    logger.info("Database tables checked and created if needed")

def get_table_columns(conn, table_name):
    """Get column names for a specified table."""
    c = conn.cursor()
    c.execute(f"PRAGMA table_info({table_name})")
    return [column[1] for column in c.fetchall()]

def get_all_refills(conn):
    """Retrieve all refill events from the database, ordered by date."""
    c = conn.cursor()
    columns = get_table_columns(conn, 'readings')
    
    c.execute(f'''
        SELECT {", ".join(columns)} 
        FROM readings 
        WHERE refill_detected = 'y' 
        ORDER BY date
    ''')
    
    results = c.fetchall()
    refills = [dict(zip(columns, row)) for row in results]
    
    logger.info(f"Found {len(refills)} refill events in the database")
    return refills

def get_actual_refill_costs(conn):
    """Retrieve all actual refill costs from the database."""
    c = conn.cursor()
    c.execute('''
        SELECT refill_date, actual_volume_litres, actual_ppl, total_cost, invoice_ref, notes, entry_date
        FROM actual_refill_costs
        ORDER BY refill_date
    ''')
    
    results = c.fetchall()
    actual_costs = [
        {
            'refill_date': row[0],
            'actual_volume_litres': row[1],
            'actual_ppl': row[2],
            'total_cost': row[3],
            'invoice_ref': row[4],
            'notes': row[5],
            'entry_date': row[6]
        }
        for row in results
    ]
    
    logger.info(f"Found {len(actual_costs)} actual refill cost records in the database")
    return actual_costs

def get_readings_between_dates(conn, start_date, end_date):
    """Retrieve all readings between two dates."""
    c = conn.cursor()
    columns = get_table_columns(conn, 'readings')
    
    c.execute(f'''
        SELECT {", ".join(columns)} 
        FROM readings 
        WHERE date BETWEEN ? AND ? 
        ORDER BY date
    ''', (start_date, end_date))
    
    results = c.fetchall()
    readings = [dict(zip(columns, row)) for row in results]
    
    # Log the first and last reading to help debug consumption issues
    if readings:
        logger.debug(f"First reading at {readings[0]['date']}: {readings[0]['litres_remaining']:.2f} liters")
        logger.debug(f"Last reading at {readings[-1]['date']}: {readings[-1]['litres_remaining']:.2f} liters")
        logger.debug(f"Found {len(readings)} readings between {start_date} and {end_date}")
    
    return readings

def calculate_refill_amount(readings_before, refill_reading):
    """
    Calculate the amount of oil added during a refill.
    
    This handles both partial and full refills by looking at the difference
    in liters remaining before and after the refill.
    """
    if not readings_before:
        logger.warning(f"No readings found before refill on {refill_reading['date']}")
        # For the first refill in the database, we can't calculate how much was added
        return None
    
    # Get the reading immediately before the refill
    reading_before = readings_before[-1]
    
    # Calculate the amount added
    liters_before = reading_before['litres_remaining']
    liters_after = refill_reading['litres_remaining']
    liters_added = liters_after - liters_before
    
    if liters_added <= 0:
        logger.warning(f"Invalid refill amount: {liters_added} liters on {refill_reading['date']}")
        return None
    
    logger.info(f"Refill on {refill_reading['date']}: {liters_added:.2f} liters added")
    return liters_added

# Price notes:
# - Price per liter (ppl) is stored in pence in the database (e.g., 58.54 means 58.54 pence per liter)
# - For monetary calculations, we convert pence to pounds (divide by 100)
# - For display purposes, we keep ppl in pence but monetary values in pounds

def calculate_cost_for_period(readings, start_date, end_date, actual_costs=None):
    """Calculate the cost of oil consumed during a specific period."""
    if not readings or len(readings) < 2:
        logger.warning(f"Insufficient readings to calculate cost for period {start_date} to {end_date}")
        return None
    
    # Sort readings by date
    sorted_readings = sorted(readings, key=lambda x: x['date'])
    
    # Calculate total consumption
    first_reading = sorted_readings[0]
    last_reading = sorted_readings[-1]
    
    total_consumption = first_reading['litres_remaining'] - last_reading['litres_remaining']
    
    # Log detailed information about the consumption calculation
    logger.debug(f"Consumption calculation for period {start_date} to {end_date}:")
    logger.debug(f"  First reading: {first_reading['date']} - {first_reading['litres_remaining']:.2f} liters")
    logger.debug(f"  Last reading: {last_reading['date']} - {last_reading['litres_remaining']:.2f} liters")
    logger.debug(f"  Calculated consumption: {total_consumption:.2f} liters")
    
    # Handle potential negative consumption (could happen due to sensor calibration)
    if total_consumption <= 0:
        logger.warning(f"No or negative consumption detected for period {start_date} to {end_date}: {total_consumption:.2f} liters")
        logger.warning(f"This could be due to sensor calibration issues or a refill event not being detected")
        
        # For analysis purposes, we'll use a minimal consumption estimate based on historical data
        # or set a minimum threshold to allow the period to still be analyzed
        min_consumption_per_day = 0.1  # Minimal assumed consumption of 0.1 liters per day
        days = (datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S') - 
                datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')).days
        if days <= 0:
            days = 1  # Prevent division by zero
            
        estimated_consumption = days * min_consumption_per_day
        logger.warning(f"Using estimated minimal consumption of {estimated_consumption:.2f} liters for analysis purposes")
        total_consumption = estimated_consumption
    
    # Calculate average price per liter for the period
    # We'll use a weighted average based on the amount consumed at each price point
    total_cost = 0
    remaining_consumption = total_consumption
    
    # If we have no real consumption, use the last known price
    if total_consumption <= 0.1 * days:  # Using our minimal estimate
        ppl = sorted_readings[-1]['current_ppl'] / 100.0  # Convert pence to pounds
        total_cost = total_consumption * ppl
    else:
        for i in range(len(sorted_readings) - 1):
            current = sorted_readings[i]
            next_reading = sorted_readings[i+1]
            
            consumption = current['litres_remaining'] - next_reading['litres_remaining']
            if consumption > 0:
                # Use the price from the current reading
                # Convert pence per liter to pounds per liter (divide by 100)
                ppl = current['current_ppl'] / 100.0
                cost = consumption * ppl
                total_cost += cost
                remaining_consumption -= consumption
    
    # Adjust for any rounding errors
    if abs(remaining_consumption) > 0.01 and total_consumption > days * min_consumption_per_day:
        logger.warning(f"Consumption calculation mismatch: {remaining_consumption:.2f} liters unaccounted for")
    
    days = (datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S') - 
            datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')).days
    
    if days <= 0:
        logger.warning(f"Invalid date range: {start_date} to {end_date}")
        days = 1  # Prevent division by zero
    
    # Calculate days in average month from calendar (more accurate than hardcoded 30.44)
    days_in_year = 366 if datetime.now().year % 4 == 0 else 365
    days_in_month = days_in_year / 12
    
    return {
        'total_cost': round(total_cost, 2),
        'total_consumption': round(total_consumption, 2),
        'average_ppl': round((total_cost / total_consumption) * 100, 2) if total_consumption > 0 else sorted_readings[-1]['current_ppl'],
        'daily_cost': round(total_cost / days, 2),
        'daily_consumption': round(total_consumption / days, 2),
        'weekly_cost': round((total_cost / days) * 7, 2),
        'monthly_cost': round((total_cost / days) * days_in_month, 2),
        'period_days': days,
        'estimated_consumption': total_consumption <= 0.1 * days  # Flag to indicate if we're using estimated consumption
    }

def find_matching_actual_cost(refill_date, actual_costs):
    """Find the actual cost record that matches a refill date."""
    refill_dt = datetime.strptime(refill_date, '%Y-%m-%d %H:%M:%S')
    
    # First try to find an exact match
    for cost in actual_costs:
        cost_dt = datetime.strptime(cost['refill_date'], '%Y-%m-%d %H:%M:%S')
        if cost_dt == refill_dt:
            return cost
    
    # If no exact match, look for a record within 24 hours
    for cost in actual_costs:
        cost_dt = datetime.strptime(cost['refill_date'], '%Y-%m-%d %H:%M:%S')
        if abs((cost_dt - refill_dt).total_seconds()) <= 86400:  # 24 hours in seconds
            return cost
    
    return None

def get_hdd_data(conn, start_date, end_date):
    """Retrieve HDD data for a given date range."""
    c = conn.cursor()
    c.execute('''
        SELECT strftime('%Y-%m-%d', date) as day, AVG(heating_degree_days) as avg_hdd
        FROM readings 
        WHERE date BETWEEN ? AND ? 
        AND heating_degree_days IS NOT NULL
        GROUP BY day
        ORDER BY day
    ''', (start_date, end_date))
    
    # Get the data with day-level granularity
    hdd_data = dict(c.fetchall())
    
    # Log summary statistics to help diagnose issues
    if hdd_data:
        total_hdd = sum(hdd_data.values())
        avg_hdd = total_hdd / len(hdd_data) if hdd_data else 0
        logger.debug(f"HDD data for period {start_date} to {end_date}: {len(hdd_data)} days, {total_hdd:.2f} total HDD, {avg_hdd:.2f} average daily HDD")
    else:
        logger.warning(f"No valid HDD data found for period {start_date} to {end_date}")
    
    return hdd_data

def get_efficiency_data(conn, start_date, end_date):
    """Retrieve seasonal efficiency data for a given date range."""
    c = conn.cursor()
    c.execute('''
        SELECT date, seasonal_efficiency 
        FROM readings 
        WHERE date BETWEEN ? AND ? 
        AND seasonal_efficiency IS NOT NULL
        ORDER BY date
    ''', (start_date, end_date))
    return dict(c.fetchall())

def calculate_cost_metrics_with_efficiency(period_data, readings, efficiency_data):
    """Calculate additional cost metrics using efficiency data."""
    if not efficiency_data:
        return {}
    
    # Calculate average efficiency for the period
    efficiencies = list(efficiency_data.values())
    avg_efficiency = sum(efficiencies) / len(efficiencies) if efficiencies else None
    
    if not avg_efficiency:
        return {}
    
    # Calculate cost per unit of heat output
    # Assuming efficiency is in percentage (0-100)
    heat_output = period_data['total_consumption'] * (avg_efficiency / 100)
    cost_per_heat_unit = period_data['total_cost'] / heat_output if heat_output > 0 else 0
    
    return {
        'average_efficiency': round(avg_efficiency, 2),
        'heat_output_liters': round(heat_output, 2),
        'cost_per_heat_unit': round(cost_per_heat_unit, 4)
    }

def calculate_hdd_cost_metrics(period_data, hdd_data):
    """Calculate cost metrics relative to heating degree days."""
    if not hdd_data:
        return {}
    
    # Calculate total HDD for the period
    total_hdd = sum(hdd_data.values())
    
    # Add detailed diagnostic for periods with suspiciously high HDD values
    days_in_period = period_data['period_days']
    if days_in_period > 0:
        avg_daily_hdd = total_hdd / days_in_period
        if avg_daily_hdd > 10:  # Suspiciously high daily average
            logger.warning(f"Suspiciously high HDD values detected for period {period_data.get('start_date', 'unknown')} to {period_data.get('end_date', 'unknown')}")
            logger.warning(f"Total HDD: {total_hdd:.2f}, Average daily HDD: {avg_daily_hdd:.2f}")
            logger.warning(f"Number of HDD readings: {len(hdd_data)}, Days in period: {days_in_period}")
            
            # Check for potential duplicate dates
            date_counts = {}
            for date in hdd_data.keys():
                date_str = date.split()[0]  # Extract date part only
                date_counts[date_str] = date_counts.get(date_str, 0) + 1
            
            duplicates = {d: c for d, c in date_counts.items() if c > 1}
            if duplicates:
                logger.warning(f"Found duplicate dates in HDD data: {duplicates}")
    
    if total_hdd == 0:
        return {}
    
    # Calculate costs per HDD
    cost_per_hdd = period_data['total_cost'] / total_hdd
    consumption_per_hdd = period_data['total_consumption'] / total_hdd
    
    return {
        'total_hdd': round(total_hdd, 2),
        'cost_per_hdd': round(cost_per_hdd, 4),
        'consumption_per_hdd': round(consumption_per_hdd, 4)
    }

def calculate_energy_metrics(period_data, efficiency_data=None):
    """Calculate energy metrics in kWh based on oil consumption."""
    if 'total_consumption' not in period_data or period_data['total_consumption'] <= 0:
        return {}
    
    # Calculate total energy in kWh
    total_consumption_liters = period_data['total_consumption']
    total_energy_kwh = total_consumption_liters * HEATING_OIL_KWH_PER_LITER
    
    # Calculate delivered energy if efficiency data is available
    avg_efficiency = None
    if efficiency_data:
        efficiencies = list(efficiency_data.values())
        avg_efficiency = sum(efficiencies) / len(efficiencies) if efficiencies else None
    
    # If we don't have measured efficiency data, use a default assumption
    if not avg_efficiency:
        avg_efficiency = 0.85  # Assume 85% efficiency as a default (store as decimal 0-1)
    elif avg_efficiency > 1:
        # Convert percentage (0-100) to decimal (0-1) for consistency
        avg_efficiency = avg_efficiency / 100
    
    # Calculate useful energy delivered (efficiency as decimal 0-1)
    delivered_energy_kwh = total_energy_kwh * avg_efficiency
    
    # Calculate energy cost metrics
    total_cost = period_data['total_cost']
    cost_per_kwh = total_cost / total_energy_kwh if total_energy_kwh > 0 else 0
    cost_per_useful_kwh = total_cost / delivered_energy_kwh if delivered_energy_kwh > 0 else 0
    
    days = period_data.get('days', 1)
    if days <= 0:
        days = 1  # Prevent division by zero
    
    # Calculate daily energy from delivered energy (not total energy)
    daily_energy_kwh = delivered_energy_kwh / days
    
    return {
        'total_energy_kwh': round(total_energy_kwh, 2),
        'delivered_energy_kwh': round(delivered_energy_kwh, 2),
        'cost_per_kwh': round(cost_per_kwh, 4),
        'cost_per_useful_kwh': round(cost_per_useful_kwh, 4),
        'daily_energy_kwh': round(daily_energy_kwh, 2),
        'energy_efficiency': round(avg_efficiency, 4)  # Store as decimal (0-1) consistently
    }

def analyze_costs_between_refills(conn):
    """Analyze costs between consecutive refill events."""
    # Get all actual refill cost data
    actual_costs = get_actual_refill_costs(conn)
    
    if len(actual_costs) < 2:
        logger.warning("Insufficient refill cost records for analysis - need at least 2")
        # Try to get detected refills from sensor data as fallback
        refills = get_all_refills(conn)
        if len(refills) < 2:
            logger.warning("Insufficient refill events for cost analysis")
            return None
    else:
        # Use actual refill cost data for analysis
        logger.info(f"Using {len(actual_costs)} actual refill cost records for analysis")
        
    # Sort actual costs by date
    sorted_actual_costs = sorted(actual_costs, key=lambda x: x['refill_date'])
    
    # Log details about all refills
    logger.info(f"Analyzing {len(sorted_actual_costs)} refill events from historical data:")
    for i, refill in enumerate(sorted_actual_costs):
        logger.info(f"  Refill #{i+1}: {refill['refill_date']} - {refill['actual_volume_litres']:.2f} liters added at {refill['actual_ppl']:.2f}p/l")
    
    cost_analysis = {
        'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'refill_periods': [],
        'latest_metrics': {},
        'historical_averages': {},
        'efficiency_metrics': {},
        'weather_impact': {},
        'latest_complete_period': {}  # Store information about the most recent complete period
    }
    
    total_costs = []
    total_consumptions = []
    daily_costs = []
    total_days = 0
    
    # Collect efficiency and weather metrics across all periods
    all_cost_per_hdd = []
    all_consumption_per_hdd = []
    all_cost_per_heat_unit = []
    all_cost_per_kwh = []
    
    # If using actual costs, analyze periods between consecutive deliveries
    if len(sorted_actual_costs) >= 2:
        analyzed_periods = 0
        latest_complete_period_idx = None
        
        # Analyze each period between refills using actual cost data
        for i in range(len(sorted_actual_costs) - 1):
            current_refill = sorted_actual_costs[i]
            next_refill = sorted_actual_costs[i+1]
            
            start_date = current_refill['refill_date']
            end_date = next_refill['refill_date']
            
            logger.info(f"Analyzing period from {start_date} to {end_date} using actual costs")
            
            # Calculate days between refills
            start_dt = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
            days = (end_dt - start_dt).days
            if days <= 0:
                logger.warning(f"Invalid date range: {start_date} to {end_date}")
                days = 1  # Prevent division by zero
            
            # Get readings during this period for supplementary data
            readings = get_readings_between_dates(conn, start_date, end_date)
            hdd_data = get_hdd_data(conn, start_date, end_date)
            efficiency_data = get_efficiency_data(conn, start_date, end_date)
            
            # For historical analysis, assume the consumption equals the next delivery amount
            # This is a reasonable estimate even for partial fills, as it measures actual cost per delivery
            refill_amount = next_refill['actual_volume_litres']
            consumption = refill_amount  # Assume consumption equals next delivery
            
            # Calculate cost metrics for this period
            # We're using the actual delivery amount from the next refill as our consumption
            total_cost = next_refill['total_cost']  # Already in pounds from the database
            
            # Calculate days in average month from calendar (more accurate than hardcoded 30.44)
            days_in_year = 366 if datetime.now().year % 4 == 0 else 365
            days_in_month = days_in_year / 12
            
            # Create cost metrics like our regular calculation does
            cost_metrics = {
                'total_cost': total_cost,
                'total_consumption': refill_amount,
                'average_ppl': next_refill['actual_ppl'],
                'daily_cost': round(total_cost / days, 2),
                'daily_consumption': round(refill_amount / days, 2),
                'weekly_cost': round((total_cost / days) * 7, 2),
                'monthly_cost': round((total_cost / days) * days_in_month, 2),
                'period_days': days,
                'estimated_consumption': False
            }
            
            # Calculate additional metrics using HDD and efficiency data
            hdd_metrics = calculate_hdd_cost_metrics(cost_metrics, hdd_data)
            efficiency_metrics = calculate_cost_metrics_with_efficiency(cost_metrics, readings, efficiency_data)
            energy_metrics = calculate_energy_metrics(cost_metrics, efficiency_data)
            
            # Create period data
            period_data = {
                'start_date': start_date,
                'end_date': end_date,
                'days': days,
                'total_consumption': cost_metrics['total_consumption'],
                'average_ppl': cost_metrics['average_ppl'],
                'total_cost': cost_metrics['total_cost'],
                'daily_cost': cost_metrics['daily_cost'],
                'weekly_cost': cost_metrics['weekly_cost'],
                'monthly_cost': cost_metrics['monthly_cost'],
                'refill_amount_liters': next_refill['actual_volume_litres'],
                'refill_ppl': next_refill['actual_ppl'],
                'refill_cost': next_refill['total_cost'],
                'refill_invoice': next_refill.get('invoice_ref', ''),
                'refill_notes': next_refill.get('notes', ''),
                'used_actual_cost': True,
                'estimated_consumption': False,
                'weather_metrics': hdd_metrics,
                'efficiency_metrics': efficiency_metrics,
                'energy_metrics': energy_metrics,
                'analysis_method': 'actual_cost_records'
            }
            
            cost_analysis['refill_periods'].append(period_data)
            analyzed_periods += 1
            
            # Track this as the latest complete period (between two refills)
            latest_complete_period_idx = len(cost_analysis['refill_periods']) - 1
            
            # Collect data for historical averages
            total_costs.append(cost_metrics['total_cost'])
            total_consumptions.append(cost_metrics['total_consumption'])
            daily_costs.append(cost_metrics['daily_cost'])
            total_days += days
            
            # Collect weather and efficiency metrics
            if hdd_metrics:
                all_cost_per_hdd.append(hdd_metrics['cost_per_hdd'])
                all_consumption_per_hdd.append(hdd_metrics['consumption_per_hdd'])
            if efficiency_metrics:
                all_cost_per_heat_unit.append(efficiency_metrics['cost_per_heat_unit'])
            if energy_metrics:
                all_cost_per_kwh.append(energy_metrics['cost_per_kwh'])
                
            logger.info(f"Analysis for period {start_date} to {end_date} completed using actual costs")
            logger.info(f"  Consumption: {cost_metrics['total_consumption']:.2f} liters")
            logger.info(f"  Cost: £{cost_metrics['total_cost']:.2f}")
            logger.info(f"  Daily cost: £{cost_metrics['daily_cost']:.2f}")
        
        # Make a copy of the latest complete period data for easy access
        if latest_complete_period_idx is not None:
            cost_analysis['latest_complete_period'] = cost_analysis['refill_periods'][latest_complete_period_idx].copy()
            
        logger.info(f"Successfully analyzed {analyzed_periods} refill periods using actual cost data")
    else:
        # Fall back to original sensor-based analysis if we don't have enough actual cost records
        # This is the original analysis code which will use refill_detected events from sensor data
        refills = get_all_refills(conn)
        logger.warning("Falling back to sensor-based refill detection - results may be less accurate")
        # We would include the original analysis code here
        
    # Calculate historical averages
    if total_costs:
        avg_total_cost = sum(total_costs) / len(total_costs)
        avg_consumption = sum(total_consumptions) / len(total_consumptions)
        avg_daily_cost = sum(daily_costs) / len(daily_costs)
        
        # Calculate days in average month from calendar
        days_in_year = 366 if datetime.now().year % 4 == 0 else 365
        days_in_month = days_in_year / 12
        
        cost_analysis['historical_averages'] = {
            'average_period_cost': round(avg_total_cost, 2),
            'average_period_consumption': round(avg_consumption, 2),
            'average_daily_cost': round(avg_daily_cost, 2),
            'average_weekly_cost': round(avg_daily_cost * 7, 2),
            'average_monthly_cost': round(avg_daily_cost * days_in_month, 2),
            'average_annual_cost': round(avg_daily_cost * days_in_year, 2)
        }
        
        # Add weather and efficiency averages
        if all_cost_per_hdd:
            cost_analysis['weather_impact'] = {
                'average_cost_per_hdd': round(sum(all_cost_per_hdd) / len(all_cost_per_hdd), 4),
                'average_consumption_per_hdd': round(sum(all_consumption_per_hdd) / len(all_consumption_per_hdd), 4),
                'cost_variation_by_hdd': round(np.std(all_cost_per_hdd), 4) if len(all_cost_per_hdd) > 1 else 0
            }
        
        if all_cost_per_heat_unit:
            cost_analysis['efficiency_metrics'] = {
                'average_cost_per_heat_unit': round(sum(all_cost_per_heat_unit) / len(all_cost_per_heat_unit), 4),
                'cost_variation_by_efficiency': round(np.std(all_cost_per_heat_unit), 4) if len(all_cost_per_heat_unit) > 1 else 0
            }
        
        # Add energy metrics to historical averages
        if 'all_cost_per_kwh' in locals() and all_cost_per_kwh:
            cost_analysis['energy_metrics'] = {
                'average_cost_per_kwh': round(sum(all_cost_per_kwh) / len(all_cost_per_kwh), 4),
                'cost_variation_by_kwh': round(np.std(all_cost_per_kwh), 4) if len(all_cost_per_kwh) > 1 else 0
            }
    
    # Calculate latest metrics (based on most recent refill period)
    if cost_analysis['refill_periods']:
        # Get the most recent complete period (between last two refills)
        latest_period = cost_analysis['refill_periods'][-1]
        
        # Add a flag to indicate whether we have actual cost data for the latest refill
        has_actual_cost = latest_period.get('used_actual_cost', False)
        
        # Structure the latest metrics to focus on the most recent complete period
        cost_analysis['latest_metrics'] = {
            'period_start_date': latest_period['start_date'],
            'period_end_date': latest_period['end_date'],
            'period_days': latest_period['days'],
            'refill_date': latest_period['end_date'],
            'refill_amount': latest_period['refill_amount_liters'],
            'refill_cost': latest_period['refill_cost'],
            'refill_ppl': latest_period['refill_ppl'],
            'has_actual_cost_data': has_actual_cost,
            'refill_invoice': latest_period.get('refill_invoice', ''),
            'using_estimated_consumption': latest_period.get('estimated_consumption', False),
            'total_consumption': latest_period['total_consumption'],
            'total_cost': latest_period['total_cost'],
            'daily_cost': latest_period['daily_cost'],
            'weekly_cost': latest_period['weekly_cost'],
            'monthly_cost': latest_period['monthly_cost'],
            'days_since_refill': (datetime.now() - datetime.strptime(latest_period['end_date'], '%Y-%m-%d %H:%M:%S')).days,
            'current_ppl': sorted_actual_costs[-1]['actual_ppl'] if sorted_actual_costs else 0
        }
        
        # Add energy metrics to latest_metrics if available
        if 'energy_metrics' in latest_period and latest_period['energy_metrics']:
            cost_analysis['latest_metrics']['energy_metrics'] = latest_period['energy_metrics']
    
    # Calculate seasonal cost variations if we have enough data
    if len(cost_analysis['refill_periods']) >= 4:  # Need at least a year of data
        monthly_costs = {}
        monthly_consumption = {}
        
        for period in cost_analysis['refill_periods']:
            start = datetime.strptime(period['start_date'], '%Y-%m-%d %H:%M:%S')
            end = datetime.strptime(period['end_date'], '%Y-%m-%d %H:%M:%S')
            
            # Skip periods that span more than 60 days (unreliable for monthly analysis)
            if (end - start).days > 60:
                continue
                
            # Assign to the month that covers most of the period
            month = start.month
            if (end.month != start.month) and (end.day > 15):
                month = end.month
                
            if month not in monthly_costs:
                monthly_costs[month] = []
                monthly_consumption[month] = []
                
            # Normalize to daily values
            daily_cost = period['total_cost'] / period['days']
            daily_consumption = period['total_consumption'] / period['days']
            
            monthly_costs[month].append(daily_cost)
            monthly_consumption[month].append(daily_consumption)
        
        # Calculate average daily cost and consumption for each month
        seasonal_data = {}
        for month in range(1, 13):
            month_name = calendar.month_name[month]
            if month in monthly_costs and len(monthly_costs[month]) > 0:
                avg_daily_cost = sum(monthly_costs[month]) / len(monthly_costs[month])
                avg_daily_consumption = sum(monthly_consumption[month]) / len(monthly_consumption[month])
                
                seasonal_data[month_name] = {
                    'avg_daily_cost': round(avg_daily_cost, 2),
                    'avg_daily_consumption': round(avg_daily_consumption, 2),
                    'avg_monthly_cost': round(avg_daily_cost * calendar.monthrange(datetime.now().year, month)[1], 2)
                }
        
        if seasonal_data:
            cost_analysis['seasonal_costs'] = seasonal_data
    
    # Add statistics about actual cost data usage
    actual_count = sum(1 for period in cost_analysis['refill_periods'] if period.get('used_actual_cost', False))
    estimated_count = len(cost_analysis['refill_periods']) - actual_count
    
    cost_analysis['cost_data_stats'] = {
        'total_refill_periods': len(cost_analysis['refill_periods']),
        'periods_with_actual_cost_data': actual_count,
        'periods_with_estimated_cost': estimated_count,
        'percentage_with_actual_data': round((actual_count / len(cost_analysis['refill_periods'])) * 100, 1) if cost_analysis['refill_periods'] else 0,
        'analysis_method': 'actual_delivery_amounts' if len(sorted_actual_costs) >= 2 else 'sensor_based'
    }
    
    logger.info(f"Cost analysis completed with {len(cost_analysis['refill_periods'])} refill periods")
    return cost_analysis

def save_result_to_db(conn, result):
    """Save the cost analysis result to the database."""
    c = conn.cursor()
    
    # Save analysis date for all operations
    analysis_date = result['analysis_date']
    
    # Extract latest metrics
    latest_metrics = result.get('latest_metrics', {})
    historical_averages = result.get('historical_averages', {})
    weather_impact = result.get('weather_impact', {})
    energy_metrics = result.get('energy_metrics', {})
    efficiency_metrics = result.get('efficiency_metrics', {})
    cost_data_stats = result.get('cost_data_stats', {})
    
    try:
        # First check if energy_efficiency column exists
        c.execute("PRAGMA table_info(cost_analysis)")
        columns = [column[1] for column in c.fetchall()]
        has_energy_efficiency = 'energy_efficiency' in columns
        
        # Prepare the base SQL statement
        sql = '''
        INSERT OR REPLACE INTO cost_analysis (
            analysis_date,
            
            latest_period_start,
            latest_period_end,
            latest_period_days,
            latest_refill_amount,
            latest_refill_cost,
            latest_refill_ppl,
            latest_total_consumption,
            latest_total_cost,
            latest_daily_cost,
            latest_weekly_cost,
            latest_monthly_cost,
            days_since_refill,
            
            avg_period_cost,
            avg_period_consumption,
            avg_daily_cost,
            avg_weekly_cost,
            avg_monthly_cost,
            avg_annual_cost,
            
            avg_cost_per_hdd,
            avg_consumption_per_hdd,
            
            avg_cost_per_kwh,
            avg_daily_energy_kwh,
            
            avg_cost_per_heat_unit,
            '''
        
        # Add energy_efficiency column if it exists
        if has_energy_efficiency:
            sql += 'energy_efficiency,'
        
        sql += '''
            total_refill_periods,
            percentage_with_actual_data,
            
            analysis_data
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '''
        
        # Add placeholder for energy_efficiency if column exists
        if has_energy_efficiency:
            sql += '?, '
        
        sql += '?, ?, ?)'
        
        # Prepare parameters
        params = [
            analysis_date,
            
            latest_metrics.get('period_start_date', ''),
            latest_metrics.get('period_end_date', ''),
            latest_metrics.get('period_days', 0),
            latest_metrics.get('refill_amount', 0),
            latest_metrics.get('refill_cost', 0),
            latest_metrics.get('refill_ppl', 0),
            latest_metrics.get('total_consumption', 0),
            latest_metrics.get('total_cost', 0),
            latest_metrics.get('daily_cost', 0),
            latest_metrics.get('weekly_cost', 0),
            latest_metrics.get('monthly_cost', 0),
            latest_metrics.get('days_since_refill', 0),
            
            historical_averages.get('average_period_cost', 0),
            historical_averages.get('average_period_consumption', 0),
            historical_averages.get('average_daily_cost', 0),
            historical_averages.get('average_weekly_cost', 0),
            historical_averages.get('average_monthly_cost', 0),
            historical_averages.get('average_annual_cost', 0),
            
            weather_impact.get('average_cost_per_hdd', 0),
            weather_impact.get('average_consumption_per_hdd', 0),
            
            energy_metrics.get('average_cost_per_kwh', 0),
            # Extract daily energy from latest metrics if available
            latest_metrics.get('energy_metrics', {}).get('daily_energy_kwh', 0),
            
            efficiency_metrics.get('average_cost_per_heat_unit', 0),
        ]
        
        # Add energy_efficiency parameter if column exists
        if has_energy_efficiency:
            params.append(efficiency_metrics.get('energy_efficiency', 0))
        
        # Add remaining parameters
        params.extend([
            cost_data_stats.get('total_refill_periods', 0),
            cost_data_stats.get('percentage_with_actual_data', 0),
            
            json.dumps(result)  # Still store complete JSON for backward compatibility
        ])
        
        # Execute the query
        c.execute(sql, params)
        
    except Exception as e:
        logger.error(f"Error saving to cost_analysis table: {e}")
        # Try to save just the minimum required data if we had an error
        try:
            c.execute('''
            INSERT OR REPLACE INTO cost_analysis (analysis_date, analysis_data)
            VALUES (?, ?)
            ''', (analysis_date, json.dumps(result)))
            logger.info("Saved minimal data to cost_analysis table")
        except Exception as e2:
            logger.error(f"Could not save even minimal data: {e2}")
    
    # Save refill periods data
    for period in result.get('refill_periods', []):
        # Extract data
        weather_metrics = period.get('weather_metrics', {})
        
        try:
            c.execute('''
            INSERT OR REPLACE INTO refill_periods (
                start_date, end_date, days, total_consumption, average_ppl,
                total_cost, daily_cost, weekly_cost, monthly_cost,
                refill_amount_liters, refill_ppl, refill_cost,
                refill_invoice, refill_notes, used_actual_cost,
                analysis_date, total_hdd, cost_per_hdd, consumption_per_hdd
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                period.get('start_date', ''),
                period.get('end_date', ''),
                period.get('days', 0),
                period.get('total_consumption', 0),
                period.get('average_ppl', 0),
                period.get('total_cost', 0),
                period.get('daily_cost', 0),
                period.get('weekly_cost', 0),
                period.get('monthly_cost', 0),
                period.get('refill_amount_liters', 0),
                period.get('refill_ppl', 0),
                period.get('refill_cost', 0),
                period.get('refill_invoice', ''),
                period.get('refill_notes', ''),
                1 if period.get('used_actual_cost', False) else 0,
                analysis_date,
                weather_metrics.get('total_hdd', 0),
                weather_metrics.get('cost_per_hdd', 0),
                weather_metrics.get('consumption_per_hdd', 0)
            ))
        except Exception as e:
            logger.error(f"Error saving period data: {e}")
    
    # Save energy metrics for each period
    for period in result.get('refill_periods', []):
        if 'energy_metrics' in period and period['energy_metrics']:
            energy_data = period['energy_metrics']
            # Ensure energy_efficiency is stored as a decimal (0-1)
            energy_efficiency = energy_data.get('energy_efficiency', 0)
            
            try:
                c.execute('''
                INSERT OR REPLACE INTO energy_metrics
                (period_start, period_end, total_energy_kwh, delivered_energy_kwh, 
                 cost_per_kwh, cost_per_useful_kwh, daily_energy_kwh, energy_efficiency, analysis_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    period['start_date'],
                    period['end_date'],
                    energy_data.get('total_energy_kwh', 0),
                    energy_data.get('delivered_energy_kwh', 0),
                    energy_data.get('cost_per_kwh', 0),
                    energy_data.get('cost_per_useful_kwh', 0),
                    energy_data.get('daily_energy_kwh', 0),
                    energy_efficiency,
                    analysis_date
                ))
            except Exception as e:
                logger.error(f"Error saving energy metrics: {e}")
    
    conn.commit()
    logger.info(f"Cost analysis result saved to database with individual columns for date: {analysis_date}")

# Add a function to get the most recent cost analysis data
def get_latest_cost_analysis(conn):
    """Get the most recent cost analysis data from the database."""
    c = conn.cursor()
    c.execute('''
    SELECT * FROM cost_analysis
    ORDER BY analysis_date DESC
    LIMIT 1
    ''')
    
    result = c.fetchone()
    if not result:
        return None
    
    columns = [column[0] for column in c.description]
    return dict(zip(columns, result))

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
    """Publish the cost analysis result to the MQTT broker."""
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
            
        # Publish the complete JSON data for backwards compatibility
        complete_payload = json.dumps(result)
        logger.info(f"Attempting to publish to MQTT topic: {MQTT_TOPIC}")
        logger.debug(f"Complete payload: {complete_payload}")
        publish_result = client.publish(MQTT_TOPIC, complete_payload, qos=1, retain=True)
        
        if publish_result.is_published():
            logger.info(f"Complete message published successfully with retain flag. Message ID: {publish_result.mid}")
        else:
            logger.error(f"Failed to publish complete message. Result code: {publish_result.rc}")
            
        # Also publish individual metrics to separate topics for better Home Assistant integration
        base_topic = f"{MQTT_TOPIC}/metrics"
        
        # Latest metrics
        latest_metrics = {
            "period_days": result.get('latest_metrics', {}).get('period_days', 0),
            "refill_amount": result.get('latest_metrics', {}).get('refill_amount', 0),
            "refill_cost": result.get('latest_metrics', {}).get('refill_cost', 0),
            "refill_ppl": result.get('latest_metrics', {}).get('refill_ppl', 0),
            "total_consumption": result.get('latest_metrics', {}).get('total_consumption', 0),
            "total_cost": result.get('latest_metrics', {}).get('total_cost', 0),
            "daily_cost": result.get('latest_metrics', {}).get('daily_cost', 0),
            "weekly_cost": result.get('latest_metrics', {}).get('weekly_cost', 0),
            "monthly_cost": result.get('latest_metrics', {}).get('monthly_cost', 0),
            "days_since_refill": result.get('latest_metrics', {}).get('days_since_refill', 0)
        }
        
        # Add energy metrics if available
        if 'energy_metrics' in result.get('latest_metrics', {}):
            energy_data = result.get('latest_metrics', {}).get('energy_metrics', {})
            # Include energy metrics with proper labels
            latest_metrics.update({
                "daily_energy_kwh": energy_data.get('daily_energy_kwh', 0),
                "total_energy_kwh": energy_data.get('total_energy_kwh', 0),
                "delivered_energy_kwh": energy_data.get('delivered_energy_kwh', 0),
                "cost_per_kwh": energy_data.get('cost_per_kwh', 0),
                "energy_efficiency_pct": round(energy_data.get('energy_efficiency', 0) * 100, 2)  # Convert to percentage
            })
        
        # Historical averages
        historical_averages = {
            "avg_period_cost": result.get('historical_averages', {}).get('average_period_cost', 0),
            "avg_period_consumption": result.get('historical_averages', {}).get('average_period_consumption', 0),
            "avg_daily_cost": result.get('historical_averages', {}).get('average_daily_cost', 0),
            "avg_weekly_cost": result.get('historical_averages', {}).get('average_weekly_cost', 0),
            "avg_monthly_cost": result.get('historical_averages', {}).get('average_monthly_cost', 0),
            "avg_annual_cost": result.get('historical_averages', {}).get('average_annual_cost', 0)
        }
        
        # Weather impact metrics
        weather_metrics = {
            "avg_cost_per_hdd": result.get('weather_impact', {}).get('average_cost_per_hdd', 0),
            "avg_consumption_per_hdd": result.get('weather_impact', {}).get('average_consumption_per_hdd', 0)
        }
        
        # Energy metrics
        energy_metrics = {
            "avg_cost_per_kwh": result.get('energy_metrics', {}).get('average_cost_per_kwh', 0),
            "avg_daily_energy_kwh": result.get('energy_metrics', {}).get('average_daily_energy_kwh', 0)
        }
        
        # Efficiency metrics - convert to percentage for display
        efficiency_metrics = {
            "avg_cost_per_heat_unit": result.get('efficiency_metrics', {}).get('average_cost_per_heat_unit', 0),
            "energy_efficiency_pct": round(result.get('efficiency_metrics', {}).get('energy_efficiency', 0) * 100, 2)
        }
        
        # Stats metrics
        stats_metrics = {
            "total_refill_periods": result.get('cost_data_stats', {}).get('total_refill_periods', 0),
            "percentage_with_actual_data": result.get('cost_data_stats', {}).get('percentage_with_actual_data', 0)
        }
        
        # Combine all metrics
        all_metrics = {
            **latest_metrics,
            **historical_averages,
            **weather_metrics,
            **energy_metrics,
            **efficiency_metrics,
            **stats_metrics
        }
        
        # Publish each metric to its own topic
        successful_publishes = 0
        for key, value in all_metrics.items():
            topic = f"{base_topic}/{key}"
            # Convert floating point values to strings with 2 decimal places for consistency
            if isinstance(value, float):
                payload = f"{value:.4f}" if key.startswith("cost_per") or "efficiency" in key else f"{value:.2f}"
            else:
                payload = str(value)
                
            publish_result = client.publish(topic, payload, qos=1, retain=True)
            if publish_result.is_published():
                successful_publishes += 1
            else:
                logger.warning(f"Failed to publish metric {key} to {topic}")
        
        logger.info(f"Successfully published {successful_publishes} out of {len(all_metrics)} individual metrics to MQTT")
        
        client.loop_stop()
        client.disconnect()
        logger.info("Disconnected from MQTT broker")
        
    except Exception as e:
        logger.error(f"Failed to publish to MQTT: {e}")
        logger.exception("Exception details:")

def parse_date(date_str):
    """Parse date string in multiple formats."""
    date_formats = [
        '%d/%m/%Y',  # DD/MM/YYYY
        '%d-%m-%Y',  # DD-MM-YYYY
        '%Y-%m-%d',  # YYYY-MM-DD
        '%d/%m/%y',  # DD/MM/YY
        '%d-%m-%y'   # DD-MM-YY
    ]
    
    for fmt in date_formats:
        try:
            # Parse the date and set time to midnight
            parsed_date = datetime.strptime(date_str, fmt)
            return parsed_date.strftime('%Y-%m-%d 00:00:00')
        except ValueError:
            continue
    
    raise ValueError("Invalid date format. Please use DD/MM/YYYY or similar format")

def add_actual_refill_cost(conn):
    """Interactive CLI to add actual refill cost data."""
    print("\n=== Add Actual Refill Cost Data ===\n")
    
    # PRICE NOTE: PPL values are in pence (e.g., 58.54 means 58.54 pence per liter)
    # Cost values are in pounds
    
    # Get available refill dates from the database
    refills = get_all_refills(conn)
    if not refills:
        print("No refill events found in the database.")
        return
    
    # Get existing actual cost records
    actual_costs = get_actual_refill_costs(conn)
    existing_dates = [cost['refill_date'] for cost in actual_costs]
    
    # Display recent refills
    print("Recent refill events (detected deliveries):")
    recent_refills = sorted(refills, key=lambda x: x['date'], reverse=True)[:10]
    
    for i, refill in enumerate(recent_refills):
        refill_date = datetime.strptime(refill['date'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
        refill_amount = refill['litres_remaining']
        already_has_data = refill['date'] in existing_dates
        status = " (has actual cost data)" if already_has_data else ""
        
        print(f"{i+1}. {refill_date} - {refill_amount:.2f} liters remaining{status}")
    
    if actual_costs:
        print("\nExisting cost records (chronological order):")
        for cost in sorted(actual_costs, key=lambda x: x['refill_date']):
            date = datetime.strptime(cost['refill_date'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
            print(f"- {date}: {cost['actual_volume_litres']:.0f}L at {cost['actual_ppl']:.2f}ppl ({CURRENCY_SYMBOL}{cost['total_cost']:.2f})")
    
    print("\nOptions:")
    print("1. Select from detected deliveries above")
    print("2. Enter delivery date manually")
    choice = input("\nChoice (1-2): ").strip()
    
    if choice == '1':
        refill_idx = int(input("Enter the number of the refill (1-10): ").strip()) - 1
        if refill_idx < 0 or refill_idx >= len(recent_refills):
            print("Invalid selection.")
            return
            
        refill_date = recent_refills[refill_idx]['date']
        
    elif choice == '2':
        try:
            date_input = input("Enter delivery date (DD/MM/YYYY): ").strip()
            refill_date = parse_date(date_input)
        except ValueError as e:
            print(f"Error: {e}")
            return
    else:
        print("Invalid choice.")
        return
    
    # Check if we already have data for this date
    if refill_date in existing_dates:
        replace = input(f"Cost data already exists for {refill_date}. Replace it? (y/n): ").lower().strip()
        if replace != 'y':
            print("Operation cancelled.")
            return
    
    # Get the order details
    try:
        print("\nOrder Details:")
        order_date_str = input("Enter order date (DD/MM/YYYY) [press Enter if same as delivery]: ").strip()
        order_date = parse_date(order_date_str) if order_date_str else refill_date
        order_ref = input("Enter order reference (optional): ").strip()
        
        print("\nDelivery Details:")
        actual_volume = float(input("Enter actual volume of oil delivered (liters): ").strip())
        actual_ppl = float(input("Enter actual price per liter (ppl): ").strip())
        total_cost = float(input("Enter total cost including delivery, VAT, etc.: ").strip())
        invoice_ref = input("Enter invoice reference (optional): ").strip()
        notes = input("Enter any notes (optional): ").strip()
        
        # Confirm the data
        print("\nSummary:")
        print(f"Order Date: {datetime.strptime(order_date, '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')}")
        print(f"Order Reference: {order_ref or 'N/A'}")
        print(f"Delivery Date: {datetime.strptime(refill_date, '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')}")
        print(f"Volume: {actual_volume:.2f} liters")
        print(f"Price per liter: {actual_ppl:.2f}")
        print(f"Total Cost: {CURRENCY_SYMBOL}{total_cost:.2f}")
        print(f"Invoice Ref: {invoice_ref or 'N/A'}")
        print(f"Notes: {notes or 'N/A'}")
        
        confirm = input("\nSave this data? (y/n): ").lower().strip()
        if confirm != 'y':
            print("Operation cancelled.")
            return
        
        # Save to database
        c = conn.cursor()
        c.execute('''
        INSERT OR REPLACE INTO actual_refill_costs
        (refill_date, actual_volume_litres, actual_ppl, total_cost, invoice_ref, notes, entry_date, order_date, order_ref)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (refill_date, actual_volume, actual_ppl, total_cost, invoice_ref, notes, 
              datetime.now().strftime('%Y-%m-%d %H:%M:%S'), order_date, order_ref))
        
        conn.commit()
        print(f"Refill cost data saved successfully for delivery on {datetime.strptime(refill_date, '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')}")
        
        # Run the analysis again with the new data
        run_analysis = input("Run cost analysis with the new data? (y/n): ").lower().strip()
        if run_analysis == 'y':
            print("Running analysis...")
            result = analyze_costs_between_refills(conn)
            if result:
                save_result_to_db(conn, result)
                publish_to_mqtt(result)
                print("Analysis completed and published to MQTT.")
            else:
                print("Analysis could not be completed.")
        
    except ValueError as e:
        print(f"Error: Invalid input - {e}")
        return

def list_actual_refill_costs(conn):
    """List all actual refill cost data in the database."""
    actual_costs = get_actual_refill_costs(conn)
    
    if not actual_costs:
        print("No actual refill cost data found in the database.")
        return
    
    print("\n=== Actual Refill Cost Data ===\n")
    print(f"{'#':<4} {'Order Date':<12} {'Delivery Date':<12} {'Volume (L)':<12} {'Price (ppl)':<12} {'Total Cost':<12} {'Order Ref':<15} {'Invoice Ref':<15} {'Notes':<20}")
    print("="*110)
    
    # Sort by delivery date
    sorted_costs = sorted(actual_costs, key=lambda x: x['refill_date'])
    
    # Print each record
    for i, cost in enumerate(sorted_costs):
        order_date = datetime.strptime(cost.get('order_date', cost['refill_date']), '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
        delivery_date = datetime.strptime(cost['refill_date'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
        volume = f"{cost['actual_volume_litres']:.2f}"
        ppl = f"{cost['actual_ppl']:.2f}"
        total = f"{CURRENCY_SYMBOL}{cost['total_cost']:.2f}"
        order_ref = cost.get('order_ref', 'N/A')
        invoice = cost['invoice_ref'] or 'N/A'
        notes = cost['notes'] or 'N/A'
        
        # Print the record
        print(f"{i+1:<4} {order_date:<12} {delivery_date:<12} {volume:<12} {ppl:<12} {total:<12} {order_ref:<15} {invoice:<15} {notes[:20]:<20}")
    
    print("\nTotal Records:", len(actual_costs))
    
    # Show some basic validation checks
    print("\nValidation Checks:")
    
    # Check for unusually high or low volumes
    volumes = [cost['actual_volume_litres'] for cost in sorted_costs]
    avg_volume = sum(volumes) / len(volumes)
    for cost in sorted_costs:
        if cost['actual_volume_litres'] > avg_volume * 1.5:
            print(f"- Large delivery on {datetime.strptime(cost['refill_date'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')}: {cost['actual_volume_litres']:.0f}L (avg: {avg_volume:.0f}L)")
        elif cost['actual_volume_litres'] < avg_volume * 0.5:
            print(f"- Small delivery on {datetime.strptime(cost['refill_date'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')}: {cost['actual_volume_litres']:.0f}L (avg: {avg_volume:.0f}L)")
    
    # Check for unusual price variations
    prices = [cost['actual_ppl'] for cost in sorted_costs]
    for i in range(1, len(sorted_costs)):
        price_change = sorted_costs[i]['actual_ppl'] - sorted_costs[i-1]['actual_ppl']
        if abs(price_change) > sorted_costs[i-1]['actual_ppl'] * 0.25:  # 25% change
            date = datetime.strptime(sorted_costs[i]['refill_date'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
            print(f"- Large price change on {date}: {price_change:+.2f}ppl ({price_change/sorted_costs[i-1]['actual_ppl']*100:+.1f}%)")

def delete_actual_refill_cost(conn):
    """Delete an actual refill cost record."""
    print("\n=== Delete Actual Refill Cost Data ===\n")
    
    # Get existing actual cost records
    actual_costs = get_actual_refill_costs(conn)
    
    if not actual_costs:
        print("No actual refill cost data found in the database.")
        return
    
    # Display all records
    print("Existing records:")
    for i, cost in enumerate(sorted(actual_costs, key=lambda x: x['refill_date'])):
        date = cost['refill_date']
        volume = f"{cost['actual_volume_litres']:.2f}"
        ppl = f"{cost['actual_ppl']:.2f}"
        total = f"{CURRENCY_SYMBOL}{cost['total_cost']:.2f}"
        
        print(f"{i+1}. {date} - {volume} liters, {ppl} ppl, {total}")
    
    try:
        choice = int(input("\nEnter the number of the record to delete (0 to cancel): ").strip())
        
        if choice == 0:
            print("Operation cancelled.")
            return
            
        if choice < 1 or choice > len(actual_costs):
            print("Invalid selection.")
            return
        
        selected_cost = sorted(actual_costs, key=lambda x: x['refill_date'])[choice-1]
        
        # Confirm deletion
        print(f"\nYou are about to delete the record for {selected_cost['refill_date']}")
        confirm = input("Are you sure? (y/n): ").lower().strip()
        
        if confirm != 'y':
            print("Operation cancelled.")
            return
        
        # Delete from database
        c = conn.cursor()
        c.execute('DELETE FROM actual_refill_costs WHERE refill_date = ?', (selected_cost['refill_date'],))
        conn.commit()
        
        print(f"Record for {selected_cost['refill_date']} deleted successfully.")
        
        # Run the analysis again
        run_analysis = input("Run cost analysis after deletion? (y/n): ").lower().strip()
        if run_analysis == 'y':
            print("Running analysis...")
            result = analyze_costs_between_refills(conn)
            if result:
                save_result_to_db(conn, result)
                publish_to_mqtt(result)
                print("Analysis completed and published to MQTT.")
            else:
                print("Analysis could not be completed.")
                
    except ValueError:
        print("Invalid input. Please enter a number.")
        return

def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description='Heating Oil Cost Analysis')
    
    # Add mutually exclusive group for the main operation modes
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--add-refill', action='store_true', help='Add actual refill cost data')
    group.add_argument('--list-refills', action='store_true', help='List actual refill cost data')
    group.add_argument('--delete-refill', action='store_true', help='Delete actual refill cost data')
    group.add_argument('--clear-refills', action='store_true', help='Clear all records from the actual refill costs database')
    group.add_argument('--import-historical', action='store_true', help='Import refill data from historical_deliveries.txt')
    group.add_argument('--analyze', action='store_true', help='Run the cost analysis and publish results')
    group.add_argument('--debug-hdd', action='store_true', help='Run diagnostics on HDD data')
    group.add_argument('--list-energy', action='store_true', help='List energy metrics history')
    group.add_argument('--show-latest', action='store_true', help='Show latest analysis data from the database')
    
    return parser.parse_args()

def parse_historical_deliveries():
    """Parse the historical_deliveries.txt file and return the delivery data."""
    try:
        file_path = os.path.join('data', 'historical_deliveries.txt')
        if not os.path.exists(file_path):
            logger.error(f"Historical deliveries file not found: {file_path}")
            return []
            
        with open(file_path, 'r') as f:
            lines = f.readlines()
            
        # Skip the header line
        if len(lines) > 0:
            lines = lines[1:]
            
        deliveries = []
        for line in lines:
            try:
                # Format: Product - Quantity - Service - Delivery By - ppl - Order Total
                parts = line.strip().split(' - ')
                if len(parts) >= 6:
                    product = parts[0]
                    quantity = float(parts[1])
                    service = parts[2]
                    delivery_by_str = parts[3]  # Note: This is "delivery by" date, not actual delivery date
                    ppl = float(parts[4])
                    total_cost = float(parts[5])
                    
                    # Parse the delivery date
                    try:
                        # Format: DD/MM/YYYY
                        day, month, year = delivery_by_str.split('/')
                        delivery_by_date = f"{year}-{month}-{day} 12:00:00"  # Use noon as default time
                    except:
                        logger.warning(f"Could not parse date: {delivery_by_str}")
                        continue
                        
                    deliveries.append({
                        'product': product,
                        'quantity': quantity,
                        'service': service,
                        'delivery_by_date': delivery_by_date,
                        'delivery_by_str': delivery_by_str,
                        'ppl': ppl,
                        'total_cost': total_cost
                    })
            except Exception as e:
                logger.warning(f"Error parsing line: {line.strip()} - {e}")
                
        return deliveries
    except Exception as e:
        logger.error(f"Error reading historical deliveries: {e}")
        return []

def clear_actual_refill_costs(conn):
    """Clear all records from the actual_refill_costs table."""
    try:
        c = conn.cursor()
        c.execute("DELETE FROM actual_refill_costs")
        conn.commit()
        rows_deleted = c.rowcount
        print(f"Cleared {rows_deleted} records from the actual refill costs database.")
        return True
    except Exception as e:
        print(f"Error clearing actual refill costs: {e}")
        return False

def import_historical_deliveries(conn):
    """Import refill data from the historical_deliveries.txt file."""
    print("\n=== Import Historical Deliveries ===\n")
    
    deliveries = parse_historical_deliveries()
    if not deliveries:
        print("No historical deliveries found or could not parse the file.")
        return
        
    print(f"Found {len(deliveries)} historical deliveries:")
    for i, delivery in enumerate(deliveries):
        print(f"{i+1}. By {delivery['delivery_by_str']}: {delivery['quantity']:.0f}L at {delivery['ppl']:.2f}ppl (£{delivery['total_cost']:.2f})")
    
    # Check if there are existing records
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM actual_refill_costs")
    existing_count = c.fetchone()[0]
    
    if existing_count > 0:
        print(f"\nThere are currently {existing_count} existing refill records in the database.")
        clear_option = input("Would you like to clear all existing records before importing? (y/n): ").lower().strip()
        if clear_option == 'y':
            clear_actual_refill_costs(conn)
    
    confirm = input("\nImport these deliveries? (y/n): ").lower().strip()
    if confirm != 'y':
        print("Operation cancelled.")
        return
    
    # Get refill detection events to try to match with deliveries
    refills = get_all_refills(conn)
    print(f"\nFound {len(refills)} detected refill events in the database.")
    
    # Import the deliveries
    c = conn.cursor()
    success_count = 0
    for i, delivery in enumerate(deliveries):
        try:
            # Get the delivery by date
            delivery_by_dt = datetime.strptime(delivery['delivery_by_date'], '%Y-%m-%d %H:%M:%S')
            
            # Look for an actual refill event near this delivery (within 3 weeks before)
            matching_refill = None
            best_match_days = float('inf')
            
            for refill in refills:
                refill_dt = datetime.strptime(refill['date'], '%Y-%m-%d %H:%M:%S')
                days_diff = (delivery_by_dt - refill_dt).days
                
                # Check if this refill happened within 3 weeks before the delivery by date
                if 0 <= days_diff <= 21 and days_diff < best_match_days:
                    matching_refill = refill
                    best_match_days = days_diff
            
            # Ask user about the actual delivery date
            print(f"\nDelivery #{i+1}: {delivery['quantity']:.0f}L due by {delivery['delivery_by_str']}")
            
            delivery_date = None
            
            if matching_refill:
                refill_date_str = datetime.strptime(matching_refill['date'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
                use_refill = input(f"Found a refill event on {refill_date_str}. Use this as the delivery date? (y/n): ").lower().strip()
                
                if use_refill == 'y':
                    delivery_date = matching_refill['date']
                    tank_level = matching_refill['litres_remaining']
                    print(f"Using refill event on {refill_date_str} with tank level of {tank_level:.2f}L")
            
            if not delivery_date:
                use_input = input("Enter actual delivery date (DD/MM/YYYY) or press Enter to use delivery by date: ").strip()
                if use_input:
                    try:
                        delivery_date = parse_date(use_input)
                    except ValueError as e:
                        print(f"Invalid date format: {e}")
                        delivery_date = delivery['delivery_by_date']  # Fallback to delivery by date
                else:
                    delivery_date = delivery['delivery_by_date']  # Use delivery by date
            
            # Check if we already have this delivery
            c.execute("SELECT count(*) FROM actual_refill_costs WHERE refill_date = ?", (delivery_date,))
            if c.fetchone()[0] > 0:
                print(f"Skipping delivery on {delivery_date[:10]} - record already exists")
                continue
                
            # Add notes about delivery date
            notes = delivery['product'] + ' - ' + delivery['service']
            if delivery_date != delivery['delivery_by_date']:
                notes += f" - Delivery by: {delivery['delivery_by_str']}"
            
            # Add the delivery
            c.execute('''
            INSERT INTO actual_refill_costs
            (refill_date, actual_volume_litres, actual_ppl, total_cost, invoice_ref, notes, entry_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                delivery_date,
                delivery['quantity'],
                delivery['ppl'],
                delivery['total_cost'],
                '',  # invoice_ref
                notes,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))
            success_count += 1
            print(f"Added delivery on {delivery_date[:10]}: {delivery['quantity']:.0f}L at {delivery['ppl']:.2f}ppl")
        except Exception as e:
            print(f"Error adding delivery by {delivery['delivery_by_date'][:10]}: {e}")
    
    conn.commit()
    print(f"\nSuccessfully imported {success_count} deliveries.")
    
    # Run the analysis again with the new data
    run_analysis = input("Run cost analysis with the imported data? (y/n): ").lower().strip()
    if run_analysis == 'y':
        print("Running analysis...")
        result = analyze_costs_between_refills(conn)
        if result:
            save_result_to_db(conn, result)
            publish_to_mqtt(result)
            print("Analysis completed and published to MQTT.")
        else:
            print("Analysis could not be completed.")

def debug_hdd_data(conn):
    """Analyze HDD data for potential issues."""
    print("\n=== HDD Data Diagnostic ===\n")
    
    # Get all readings with HDD data
    c = conn.cursor()
    c.execute('''
        SELECT date, heating_degree_days
        FROM readings
        WHERE heating_degree_days IS NOT NULL
        ORDER BY date
    ''')
    
    all_hdd_data = c.fetchall()
    
    if not all_hdd_data:
        print("No HDD data found in the database.")
        return
    
    print(f"Found {len(all_hdd_data)} readings with HDD data")
    
    # Check for abnormal values
    abnormal_values = []
    for date, hdd in all_hdd_data:
        if hdd < 0 or hdd > 30:
            abnormal_values.append((date, hdd))
    
    if abnormal_values:
        print(f"\nFound {len(abnormal_values)} abnormal HDD values:")
        for date, hdd in abnormal_values[:20]:  # Show at most 20 examples
            print(f"  {date}: {hdd}")
        
        if len(abnormal_values) > 20:
            print(f"  ... and {len(abnormal_values) - 20} more")
            
        # Suggest fixing the data
        fix_abnormal = input("\nWould you like to cap abnormal values to a reasonable range? (y/n): ").lower().strip()
        if fix_abnormal == 'y':
            max_value = float(input("Enter maximum allowed HDD value (recommended: 30): ").strip() or "30")
            
            # Update abnormal values
            c.execute('''
                UPDATE readings
                SET heating_degree_days = CASE
                    WHEN heating_degree_days < 0 THEN 0
                    WHEN heating_degree_days > ? THEN ?
                    ELSE heating_degree_days
                END
                WHERE heating_degree_days IS NOT NULL
            ''', (max_value, max_value))
            
            conn.commit()
            print(f"Updated {len(abnormal_values)} abnormal HDD values")
    else:
        print("No abnormal values found.")
    
    # Check for duplicate dates
    c.execute('''
        SELECT date, COUNT(*)
        FROM readings
        WHERE heating_degree_days IS NOT NULL
        GROUP BY strftime('%Y-%m-%d', date)
        HAVING COUNT(*) > 1
    ''')
    
    duplicates = c.fetchall()
    
    if duplicates:
        print(f"\nFound {len(duplicates)} dates with multiple HDD readings:")
        for date, count in duplicates[:20]:
            print(f"  {date.split()[0]}: {count} readings")
            
        if len(duplicates) > 20:
            print(f"  ... and {len(duplicates) - 20} more")
            
        # Show more details about duplicates
        show_details = input("\nWould you like to see details of duplicate readings? (y/n): ").lower().strip()
        if show_details == 'y':
            for date, _ in duplicates[:10]:  # Limit to first 10 dates
                date_prefix = date.split()[0]
                c.execute('''
                    SELECT date, heating_degree_days 
                    FROM readings 
                    WHERE date LIKE ? AND heating_degree_days IS NOT NULL
                    ORDER BY date
                ''', (f"{date_prefix}%",))
                
                duplicate_readings = c.fetchall()
                print(f"\nReadings for {date_prefix}:")
                for d, hdd in duplicate_readings:
                    print(f"  {d}: {hdd}")
    else:
        print("No duplicate date readings found.")
    
    # Check for recent abnormal values specifically
    current_year = datetime.now().year
    c.execute('''
        SELECT date, heating_degree_days
        FROM readings
        WHERE date >= ? AND heating_degree_days IS NOT NULL
        ORDER BY date
    ''', (f"{current_year}-01-01 00:00:00",))
    
    recent_readings = c.fetchall()
    
    if recent_readings:
        print(f"\nRecent HDD readings (from {current_year}):")
        # Calculate statistics
        recent_hdds = [hdd for _, hdd in recent_readings]
        avg_hdd = sum(recent_hdds) / len(recent_hdds)
        max_hdd = max(recent_hdds)
        
        print(f"  Total readings: {len(recent_readings)}")
        print(f"  Average HDD: {avg_hdd:.2f}")
        print(f"  Maximum HDD: {max_hdd:.2f}")
        
        # Show the most recent ones
        print("\nMost recent 10 readings:")
        for date, hdd in recent_readings[-10:]:
            print(f"  {date}: {hdd}")
    else:
        print(f"No HDD readings found for {current_year}")
        
    # Run analysis without publishing to check for issues
    run_analysis = input("\nWould you like to run a test analysis to check calculations? (y/n): ").lower().strip()
    if run_analysis == 'y':
        result = analyze_costs_between_refills(conn)
        if result and 'refill_periods' in result:
            print("\nHDD and Energy metrics in refill periods:")
            for i, period in enumerate(result['refill_periods']):
                start = period['start_date']
                end = period['end_date']
                weather_metrics = period.get('weather_metrics', {})
                energy_metrics = period.get('energy_metrics', {})
                
                print(f"Period {i+1}: {start} to {end} ({period.get('days', 0)} days)")
                
                if weather_metrics:
                    total_hdd = weather_metrics.get('total_hdd', 0)
                    cost_per_hdd = weather_metrics.get('cost_per_hdd', 0)
                    days = period.get('days', 0)
                    avg_daily_hdd = total_hdd / days if days > 0 else 0
                    
                    print(f"  HDD Metrics:")
                    print(f"    Total HDD: {total_hdd}")
                    print(f"    Avg daily HDD: {avg_daily_hdd:.2f}")
                    print(f"    Cost per HDD: {cost_per_hdd}")
                else:
                    print(f"  No HDD data")
                
                if energy_metrics:
                    print(f"  Energy Metrics:")
                    print(f"    Total Energy: {energy_metrics.get('total_energy_kwh', 0):.2f} kWh")
                    print(f"    Delivered Energy: {energy_metrics.get('delivered_energy_kwh', 0):.2f} kWh")
                    print(f"    Cost per kWh: {energy_metrics.get('cost_per_kwh', 0):.4f} {CURRENCY_SYMBOL}/kWh")
                    print(f"    Daily Energy: {energy_metrics.get('daily_energy_kwh', 0):.2f} kWh/day")
                    print(f"    Efficiency: {energy_metrics.get('energy_efficiency', 0):.2f}%")
                else:
                    print(f"  No energy metrics")

# Add a function to retrieve energy metrics from the database
def get_energy_metrics(conn, start_date=None, end_date=None):
    """Retrieve energy metrics from the database, optionally filtered by date range."""
    c = conn.cursor()
    
    query = "SELECT * FROM energy_metrics"
    params = []
    
    if start_date and end_date:
        query += " WHERE period_start >= ? AND period_end <= ?"
        params = [start_date, end_date]
    elif start_date:
        query += " WHERE period_start >= ?"
        params = [start_date]
    elif end_date:
        query += " WHERE period_end <= ?"
        params = [end_date]
    
    query += " ORDER BY period_start"
    
    c.execute(query, params)
    
    columns = [column[0] for column in c.description]
    results = [dict(zip(columns, row)) for row in c.fetchall()]
    
    return results

# Add a function to display energy metrics
def list_energy_metrics(conn):
    """List all energy metrics stored in the database."""
    print("\n=== Energy Metrics History ===\n")
    
    energy_metrics = get_energy_metrics(conn)
    
    if not energy_metrics:
        print("No energy metrics found in the database.")
        return
    
    print(f"Found {len(energy_metrics)} energy metric records:")
    print(f"{'Period':<40} {'Total kWh':<12} {'Delivered kWh':<15} {'Cost/kWh':<12} {'Daily kWh':<12} {'Efficiency':<10}")
    print("=" * 100)
    
    for metrics in energy_metrics:
        period_start = datetime.strptime(metrics['period_start'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
        period_end = datetime.strptime(metrics['period_end'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
        period = f"{period_start} to {period_end}"
        
        total_kwh = f"{metrics['total_energy_kwh']:.2f}"
        delivered_kwh = f"{metrics['delivered_energy_kwh']:.2f}"
        cost_per_kwh = f"{CURRENCY_SYMBOL}{metrics['cost_per_kwh']:.4f}"
        daily_kwh = f"{metrics['daily_energy_kwh']:.2f}"
        
        # Convert efficiency from decimal to percentage for display if needed
        efficiency_value = metrics.get('energy_efficiency', 0)
        if efficiency_value < 1:  # If stored as decimal (0-1)
            efficiency = f"{efficiency_value * 100:.1f}%"
        else:  # If already stored as percentage (0-100)
            efficiency = f"{efficiency_value:.1f}%"
        
        print(f"{period:<40} {total_kwh:<12} {delivered_kwh:<15} {cost_per_kwh:<12} {daily_kwh:<12} {efficiency:<10}")
    
    # Calculate and display averages
    if energy_metrics:
        print("\nAverages:")
        avg_total_kwh = sum(m['total_energy_kwh'] for m in energy_metrics) / len(energy_metrics)
        avg_delivered_kwh = sum(m['delivered_energy_kwh'] for m in energy_metrics) / len(energy_metrics)
        avg_cost_per_kwh = sum(m['cost_per_kwh'] for m in energy_metrics) / len(energy_metrics)
        avg_daily_kwh = sum(m['daily_energy_kwh'] for m in energy_metrics) / len(energy_metrics)
        
        # Handle different efficiency formats
        avg_efficiency = sum(m.get('energy_efficiency', 0) for m in energy_metrics) / len(energy_metrics)
        if avg_efficiency < 1:  # If stored as decimal (0-1)
            efficiency_display = f"{avg_efficiency * 100:.1f}%"
        else:  # If already stored as percentage (0-100)
            efficiency_display = f"{avg_efficiency:.1f}%"
        
        print(f"{'Average':<40} {avg_total_kwh:.2f}     {avg_delivered_kwh:.2f}         {CURRENCY_SYMBOL}{avg_cost_per_kwh:.4f}     {avg_daily_kwh:.2f}     {efficiency_display}")

# Add a function to display formatted cost analysis data
def display_cost_analysis(analysis_data):
    """Display formatted cost analysis data."""
    if not analysis_data:
        print("No cost analysis data found.")
        return
    
    print("\n=== Latest Cost Analysis ===")
    print(f"Analysis Date: {analysis_data['analysis_date']}")
    
    # Latest period data
    print("\nLatest Period:")
    period_start = analysis_data.get('latest_period_start', '')
    period_end = analysis_data.get('latest_period_end', '')
    if period_start and period_end:
        start_date = datetime.strptime(period_start, '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
        end_date = datetime.strptime(period_end, '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
        print(f"  Period: {start_date} to {end_date} ({analysis_data.get('latest_period_days', 0)} days)")
    else:
        print("  No period data available")
    
    print(f"  Refill Amount: {analysis_data.get('latest_refill_amount', 0):.2f} liters")
    print(f"  Refill Cost: {CURRENCY_SYMBOL}{analysis_data.get('latest_refill_cost', 0):.2f}")
    print(f"  Price per Liter: {analysis_data.get('latest_refill_ppl', 0):.2f}p")
    print(f"  Total Consumption: {analysis_data.get('latest_total_consumption', 0):.2f} liters")
    print(f"  Total Cost: {CURRENCY_SYMBOL}{analysis_data.get('latest_total_cost', 0):.2f}")
    print(f"  Daily Cost: {CURRENCY_SYMBOL}{analysis_data.get('latest_daily_cost', 0):.2f}")
    print(f"  Weekly Cost: {CURRENCY_SYMBOL}{analysis_data.get('latest_weekly_cost', 0):.2f}")
    print(f"  Monthly Cost: {CURRENCY_SYMBOL}{analysis_data.get('latest_monthly_cost', 0):.2f}")
    print(f"  Days Since Last Refill: {analysis_data.get('days_since_refill', 0)}")
    
    # Historical averages
    print("\nHistorical Averages:")
    print(f"  Average Period Cost: {CURRENCY_SYMBOL}{analysis_data.get('avg_period_cost', 0):.2f}")
    print(f"  Average Period Consumption: {analysis_data.get('avg_period_consumption', 0):.2f} liters")
    print(f"  Average Daily Cost: {CURRENCY_SYMBOL}{analysis_data.get('avg_daily_cost', 0):.2f}")
    print(f"  Average Weekly Cost: {CURRENCY_SYMBOL}{analysis_data.get('avg_weekly_cost', 0):.2f}")
    print(f"  Average Monthly Cost: {CURRENCY_SYMBOL}{analysis_data.get('avg_monthly_cost', 0):.2f}")
    print(f"  Average Annual Cost: {CURRENCY_SYMBOL}{analysis_data.get('avg_annual_cost', 0):.2f}")
    
    # Weather and energy metrics
    print("\nWeather & Energy Metrics:")
    if analysis_data.get('avg_cost_per_hdd', 0) > 0:
        print(f"  Average Cost per HDD: {CURRENCY_SYMBOL}{analysis_data.get('avg_cost_per_hdd', 0):.4f}")
        print(f"  Average Consumption per HDD: {analysis_data.get('avg_consumption_per_hdd', 0):.4f} liters")
    else:
        print("  No weather data available")
    
    if analysis_data.get('avg_cost_per_kwh', 0) > 0:
        print(f"  Average Cost per kWh: {CURRENCY_SYMBOL}{analysis_data.get('avg_cost_per_kwh', 0):.4f}")
        print(f"  Average Daily Energy: {analysis_data.get('avg_daily_energy_kwh', 0):.2f} kWh")
        
        # Try to get energy efficiency from various possible locations
        energy_efficiency = None
        # Check for column in database result
        if 'energy_efficiency' in analysis_data:
            energy_efficiency = analysis_data.get('energy_efficiency', 0)
        # Check in JSON data
        elif 'analysis_data' in analysis_data:
            try:
                json_data = json.loads(analysis_data['analysis_data'])
                if 'efficiency_metrics' in json_data and 'energy_efficiency' in json_data['efficiency_metrics']:
                    energy_efficiency = json_data['efficiency_metrics']['energy_efficiency']
            except:
                pass
                
        if energy_efficiency is not None:
            # Convert to percentage if stored as decimal
            if energy_efficiency < 1:
                efficiency_pct = energy_efficiency * 100
            else:
                efficiency_pct = energy_efficiency
            print(f"  Energy Efficiency: {efficiency_pct:.1f}%")
    else:
        print("  No energy data available")
    
    # Efficiency metrics
    if analysis_data.get('avg_cost_per_heat_unit', 0) > 0:
        print(f"  Average Cost per Heat Unit: {CURRENCY_SYMBOL}{analysis_data.get('avg_cost_per_heat_unit', 0):.4f}")
    
    # Stats
    print("\nStatistics:")
    print(f"  Total Refill Periods: {analysis_data.get('total_refill_periods', 0)}")
    print(f"  Percentage with Actual Data: {analysis_data.get('percentage_with_actual_data', 0):.1f}%")

# Add a function to show the latest analysis from the database
def show_latest_analysis(conn):
    """Show the latest analysis data from the database."""
    analysis_data = get_latest_cost_analysis(conn)
    display_cost_analysis(analysis_data)
    
    # Check if we should also show periods
    show_periods = input("\nWould you like to see detailed period data? (y/n): ").lower().strip()
    if show_periods == 'y':
        c = conn.cursor()
        c.execute('''
        SELECT * FROM refill_periods
        WHERE analysis_date = ?
        ORDER BY start_date
        ''', (analysis_data['analysis_date'],))
        
        periods = [dict(zip([column[0] for column in c.description], row)) for row in c.fetchall()]
        
        if periods:
            print("\n=== Refill Periods ===")
            for i, period in enumerate(periods):
                start_date = datetime.strptime(period['start_date'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
                end_date = datetime.strptime(period['end_date'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
                
                print(f"\nPeriod {i+1}: {start_date} to {end_date} ({period['days']} days)")
                print(f"  Consumption: {period['total_consumption']:.2f} liters")
                print(f"  Total Cost: {CURRENCY_SYMBOL}{period['total_cost']:.2f}")
                print(f"  Average ppl: {period['average_ppl']:.2f}p")
                print(f"  Daily Cost: {CURRENCY_SYMBOL}{period['daily_cost']:.2f}")
                
                if period['total_hdd'] > 0:
                    print(f"  Total HDD: {period['total_hdd']:.2f}")
                    print(f"  Cost per HDD: {CURRENCY_SYMBOL}{period['cost_per_hdd']:.4f}")
                
                # Get energy metrics for this period
                c.execute('''
                SELECT * FROM energy_metrics
                WHERE period_start = ? AND period_end = ?
                ''', (period['start_date'], period['end_date']))
                
                energy = c.fetchone()
                if energy:
                    energy_dict = dict(zip([column[0] for column in c.description], energy))
                    print(f"  Total Energy: {energy_dict['total_energy_kwh']:.2f} kWh")
                    print(f"  Delivered Energy: {energy_dict['delivered_energy_kwh']:.2f} kWh")
                    print(f"  Daily Energy: {energy_dict['daily_energy_kwh']:.2f} kWh/day")
                    print(f"  Cost per kWh: {CURRENCY_SYMBOL}{energy_dict['cost_per_kwh']:.4f}")
                    
                    # Display efficiency as percentage, handling both formats
                    efficiency_value = energy_dict.get('energy_efficiency', 0)
                    if efficiency_value < 1:  # If stored as decimal (0-1)
                        efficiency_display = f"{efficiency_value * 100:.1f}%"
                    else:  # If already stored as percentage (0-100)
                        efficiency_display = f"{efficiency_value:.1f}%"
                    print(f"  Efficiency: {efficiency_display}")

if __name__ == '__main__':
    try:
        args = parse_arguments()
        
        with get_db_connection(DB_PATH) as conn:
            setup_database(conn)
            
            if args.add_refill:
                add_actual_refill_cost(conn)
            elif args.list_refills:
                list_actual_refill_costs(conn)
            elif args.delete_refill:
                delete_actual_refill_cost(conn)
            elif args.clear_refills:
                print("\n=== Clear Actual Refill Costs ===\n")
                confirm = input("Are you sure you want to clear all refill cost records? This cannot be undone. (y/n): ").lower().strip()
                if confirm == 'y':
                    clear_actual_refill_costs(conn)
                else:
                    print("Operation cancelled.")
            elif args.import_historical:
                import_historical_deliveries(conn)
            elif args.debug_hdd:
                debug_hdd_data(conn)
            elif args.list_energy:
                list_energy_metrics(conn)
            elif args.show_latest:
                show_latest_analysis(conn)
            elif args.analyze:
                result = analyze_costs_between_refills(conn)
                if result:
                    save_result_to_db(conn, result)
                    publish_to_mqtt(result)
                    print("Analysis completed successfully and published to MQTT.")
                else:
                    print("Analysis could not be completed due to insufficient data.")
            else:
                # Default behavior (no arguments) - run analysis
                result = analyze_costs_between_refills(conn)
                if result:
                    save_result_to_db(conn, result)
                    publish_to_mqtt(result)
                    logger.info("Cost analysis completed successfully")
                else:
                    logger.info("Cost analysis not completed due to errors or insufficient data.")
            
    except Exception as e:
        logger.error(f"Error during cost analysis: {e}")
        logger.exception("Exception details:")
        print(f"Error: {e}")
        
    time.sleep(2) 