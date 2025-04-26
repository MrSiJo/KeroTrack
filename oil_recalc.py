#!/usr/bin/env python3

"""
This script recalculates values in the oil tank database.
It updates daily consumption, heating degree days, and other calculated fields.
Useful for fixing data issues or after changing calculation methods.
"""

import sqlite3
import os
import sys
import logging
from datetime import datetime, timedelta
from db_connection import get_db_connection
from utils.config_loader import load_config, get_config_value
from functools import lru_cache
import requests
from bs4 import BeautifulSoup
import json

# Load configuration
config = load_config()

# Set up logging
log_dir = get_config_value(config, 'logging', 'directory', default="logs")
os.makedirs(log_dir, exist_ok=True)
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = os.path.join(log_dir, f"oil_recalc_{timestamp}.log")

logger = logging.getLogger(__name__)
logger.setLevel(get_config_value(config, 'logging', 'level', default="INFO"))

# Clear existing handlers
logger.handlers = []

# Create handlers
file_handler = logging.FileHandler(log_file)
console_handler = logging.StreamHandler()

# Set level for handlers
file_handler.setLevel(logging.INFO)
console_handler.setLevel(logging.INFO)

# Create formatters
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add handlers to logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Database configuration
DB_PATH = get_config_value(config, 'database', 'path', default='data/KeroTrack_data.db')

# Load constants from config
TANK_CAPACITY = get_config_value(config, 'tank', 'capacity')
CURRENCY_SYMBOL = get_config_value(config, 'currency', 'symbol', default='£')

# Define constants from config file
REFERENCE_TEMP = get_config_value(config, 'analysis', 'reference_temperature')
THERMAL_EXPANSION_COEFF = get_config_value(config, 'analysis', 'thermal_expansion_coefficient')
OIL_DENSITY_AT_15C = get_config_value(config, 'analysis', 'oil_density_at_15c')
TANK_MATERIAL_CONDUCTIVITY = get_config_value(config, 'analysis', 'tank_material_conductivity')
TANK_WALL_THICKNESS = get_config_value(config, 'analysis', 'tank_wall_thickness')
OIL_SPECIFIC_HEAT = get_config_value(config, 'analysis', 'oil_specific_heat')

# Tank Dimensions (External)
LENGTH = get_config_value(config, 'tank', 'length')
WIDTH = get_config_value(config, 'tank', 'width')
HEIGHT = get_config_value(config, 'tank', 'height')
THERMAL_COEFF = get_config_value(config, 'tank', 'thermal_coefficient')

TANK_VOLUME = (LENGTH / 100) * (WIDTH / 100) * (HEIGHT / 100)

def calculate_hdd(temperature):
    base_temperature = get_config_value(config, 'analysis', 'hdd_base_temperature', default=15.5)
    return max(0, base_temperature - temperature)

def detect_refill(current_litres, previous_litres, current_air_gap, previous_air_gap):
    refill_threshold = get_config_value(config, 'detection', 'refill_threshold', default=100)
    if previous_litres is None or previous_air_gap is None:
        return 'n'
    volume_increase = current_litres - previous_litres
    air_gap_decrease = previous_air_gap - current_air_gap  # A decrease in air gap means an increase in oil level
    return 'y' if volume_increase >= refill_threshold and air_gap_decrease > 5 else 'n'

def detect_leak(current_litres, previous_litres, current_date, previous_date):
    if previous_litres is None or previous_date is None:
        return 'n'
    
    time_difference = current_date - previous_date
    if time_difference > timedelta(days=1):
        return 'n'
    
    leak_threshold = get_config_value(config, 'detection', 'leak_threshold', default=100)
    leak_rate = get_config_value(config, 'detection', 'leak_rate_per_day', default=10)
    
    expected_loss = leak_rate * time_difference.total_seconds() / 86400  # Convert seconds to days
    actual_loss = previous_litres - current_litres
    
    return 'y' if actual_loss > expected_loss and actual_loss >= leak_threshold else 'n'

def calculate_seasonal_efficiency(month):
    # Simple seasonal efficiency model
    if month in [12, 1, 2]:  # Winter
        return 0.95
    elif month in [3, 4, 5, 9, 10, 11]:  # Spring and Autumn
        return 0.97
    else:  # Summer
        return 0.99

def thermal_correction(temp):
    return (temp - 15) * THERMAL_COEFF

def corrected_litres(air_gap, oil_temp):
    if air_gap <= 1:  # Changed from 0.01 to 1 cm tolerance
        return TANK_CAPACITY
    oil_depth = HEIGHT - air_gap  # Remove the division by 100
    oil_volume = (LENGTH / 100) * (WIDTH / 100) * (oil_depth / 100)  # Convert all dimensions to meters
    
    # Calculate mass of oil at current temperature
    mass = oil_volume * density_correction(oil_temp)
    
    # Calculate volume at reference temperature
    volume_at_ref_temp = mass / OIL_DENSITY_AT_15C
    
    return round(volume_at_ref_temp * 1000, 1)  # Convert m³ to litres

def density_correction(temp):
    # Estimate density change with temperature
    return OIL_DENSITY_AT_15C / (1 + THERMAL_EXPANSION_COEFF * (temp - REFERENCE_TEMP))

def calculate_compensated_volume(air_gap_cm, temperature):
    oil_height = HEIGHT - air_gap_cm
    raw_volume = (oil_height / HEIGHT) * TANK_CAPACITY
    compensated_volume = raw_volume / (1 + THERMAL_EXPANSION_COEFF * (temperature - REFERENCE_TEMP))
    return min(compensated_volume, TANK_CAPACITY)  # Ensure we don't exceed tank capacity

def smooth_volume(current_volume, previous_volumes, window_size=5):
    all_volumes = previous_volumes + [current_volume]
    return sum(all_volumes[-window_size:]) / min(len(all_volumes), window_size)

def sanity_check(current_volume, previous_volume, current_temp, current_time, previous_time):
    REFILL_THRESHOLD = get_config_value(config, 'detection', 'refill_threshold')
    MAX_DAILY_CONSUMPTION_COLD = get_config_value(config, 'detection', 'max_daily_consumption_cold')
    MAX_DAILY_CONSUMPTION_WARM = get_config_value(config, 'detection', 'max_daily_consumption_warm')
    WARM_TEMPERATURE_THRESHOLD = get_config_value(config, 'detection', 'warm_temperature_threshold')
    
    time_diff = current_time - previous_time
    days_passed = time_diff.total_seconds() / (24 * 3600)
    
    if current_volume > previous_volume + REFILL_THRESHOLD:
        return current_volume, 'y'  # Refill detected
    
    max_daily_consumption = MAX_DAILY_CONSUMPTION_WARM if current_temp > WARM_TEMPERATURE_THRESHOLD else MAX_DAILY_CONSUMPTION_COLD
    expected_max_consumption = max_daily_consumption * days_passed
    actual_consumption = previous_volume - current_volume
    
    if actual_consumption > expected_max_consumption:
        logger.warning(f"Unusually high consumption detected: {actual_consumption:.2f} liters in {days_passed:.2f} days")
        return previous_volume - expected_max_consumption, 'n'
    
    return current_volume, 'n'

def validate_air_gap(air_gap, depth, previous_air_gap=None):
    if previous_air_gap is not None and abs(air_gap - previous_air_gap) > 10:  # 10 cm tolerance
        logger.warning(f"Large change in air_gap detected: {previous_air_gap} -> {air_gap}. Using previous value.")
        return previous_air_gap
    if abs(air_gap - depth) > 1:  # Allow for small discrepancies
        logger.warning(f"Inconsistent air_gap ({air_gap}) and depth ({depth}). Using smaller value.")
    return min(air_gap, depth)  # Use the smaller value to be conservative

def validate_litres_remaining(litres):
    return min(litres, TANK_CAPACITY)

def standardize_detection(value):
    return 'y' if value in ['y', '1', 1, True] else 'n'

def decode_signal_quality(rssi):
    """Interpret RSSI value"""
    if rssi >= -50:
        return "Excellent"
    elif rssi >= -70:
        return "Good"
    elif rssi >= -90:
        return "Fair"
    else:
        return "Poor"

def decode_status(status):
    """Decode Watchman Sonic Advanced status byte"""
    status_map = {
        192: "Initial sync (20min fast reporting)",  # 0xC0
        128: "Post-sync calibration",                # 0x80
        144: "Transitional state",                   # 0x90
        152: "Normal operation"                      # 0x98
    }
    return status_map.get(status, f"Unknown status: {status}")

def detect_sudden_drop(current_air_gap, current_time, conn):
    """
    Implement Watchman Sonic Advanced sudden drop detection logic
    """
    MIN_DISTANCE_FROM_SENSOR = 25  # cm
    SUDDEN_DROP_THRESHOLD = 1.5  # cm per hour
    LEARNING_PERIOD_HOURS = 24
    
    if current_air_gap < MIN_DISTANCE_FROM_SENSOR:
        logger.info("Oil level too close to sensor for sudden drop detection")
        return False
        
    cursor = conn.cursor()
    cursor.execute("""
        SELECT air_gap_cm, datetime(date) 
        FROM readings 
        WHERE date >= datetime(?, '-1 hour')
        ORDER BY date ASC
    """, (current_time,))
    
    readings = cursor.fetchall()
    
    cursor.execute("""
        SELECT COUNT(*) 
        FROM readings 
        WHERE date >= datetime(?, '-24 hours')
    """, (current_time,))
    
    history_count = cursor.fetchone()[0]
    if history_count < (24 * 2):
        logger.info("Still in learning period for sudden drop detection")
        return False
    
    if len(readings) >= 2:
        first_reading = readings[0]
        last_reading = readings[-1]
        
        time_diff = (datetime.strptime(last_reading[1], '%Y-%m-%d %H:%M:%S') - 
                    datetime.strptime(first_reading[1], '%Y-%m-%d %H:%M:%S'))
        hours_elapsed = time_diff.total_seconds() / 3600
        
        if hours_elapsed > 0:
            change_rate = (last_reading[0] - first_reading[0]) / hours_elapsed
            if change_rate >= SUDDEN_DROP_THRESHOLD:
                logger.warning(f"Sudden drop detected: {change_rate:.2f} cm/hour")
                return True
    return False

def process(reading, mode):
    """
    Process readings and maintain existing MQTT output format
    """
    try:
        # Get current reading values
        current_date = datetime.strptime(reading['time'], '%Y-%m-%d %H:%M:%S')
        current_air_gap = float(reading['depth_cm'])
        current_temp = float(reading['temperature_C'])
        
        # Connect to database first
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Calculate current volume using the original function
        current_litres = calculate_compensated_volume(current_air_gap, current_temp)
        
        # Enhanced logging of raw payload details
        if 'rssi' in reading:
            signal_quality = decode_signal_quality(reading['rssi'])
            logger.info(f"Signal strength: {reading['rssi']} dBm ({signal_quality})")
            
        if 'status' in reading:
            raw_flags = reading['status']
            status_desc = decode_status(raw_flags)
            logger.info(f"Sensor status: {status_desc} ({raw_flags})")
        
        # Get previous reading
        cursor.execute("""
            SELECT date, litres_remaining, air_gap_cm 
            FROM readings 
            ORDER BY date DESC 
            LIMIT 1
        """)
        prev_reading = cursor.fetchone()
        
        # Initialize values
        litres_used = 0.0
        prev_litres = None
        prev_air_gap = None
        prev_date = None
        
        if prev_reading:
            prev_date = datetime.strptime(prev_reading[0], '%Y-%m-%d %H:%M:%S')
            prev_litres = float(prev_reading[1])
            prev_air_gap = float(prev_reading[2])
            litres_used = max(0, prev_litres - current_litres)
        
        # Calculate percentage and bars
        percentage = (current_litres / TANK_CAPACITY) * 100
        bars_remaining = calculate_bars(percentage)
        
        # Get current price per litre
        prices = fetch_ppl()
        current_ppl = calculate_ppl(current_litres, prices) if prices else None
        
        # Prepare output
        output = {
            "date": current_date.strftime('%Y-%m-%d %H:%M:%S'),
            "id": reading['id'],
            "temperature": current_temp,
            "litres_remaining": round(current_litres, 1),
            "litres_used_since_last": round(litres_used, 1),
            "percentage_remaining": round(percentage, 1),
            "oil_depth_cm": round(HEIGHT - current_air_gap, 1),
            "air_gap_cm": round(current_air_gap, 1),
            "current_ppl": current_ppl,
            "cost_used": f"{(litres_used * current_ppl / 100):.2f}" if current_ppl else "0.00",
            "cost_to_fill": f"{((TANK_CAPACITY - current_litres) * current_ppl / 100):.2f}" if current_ppl else "0.00",
            "heating_degree_days": calculate_hdd(current_temp),
            "seasonal_efficiency": calculate_seasonal_efficiency(current_date.month),
            "refill_detected": detect_refill(current_litres, prev_litres, current_air_gap, prev_air_gap),
            "leak_detected": detect_leak(current_litres, prev_litres, current_date, prev_date),
            "raw_flags": raw_flags if 'status' in reading else None,
            "litres_to_order": round(TANK_CAPACITY - current_litres, 1),
            "bars_remaining": bars_remaining
        }
        
        conn.close()
        return json.dumps(output)
        
    except Exception as e:
        logger.error(f"Error processing reading: {e}", exc_info=True)
        return None

def main():
    parser = argparse.ArgumentParser(description="Process oil tank readings")
    parser.add_argument("--mode", choices=["sqlite", "json"], default="sqlite",
                        help="Output mode: sqlite (default) or json")
    args = parser.parse_args()

    logger.setLevel(logging.INFO)
    
    process_input(sys.stdin, args.mode)

def process_input(input_stream, mode):
    for line in input_stream:
        try:
            reading = json.loads(line)
            if reading['model'] == 'Oil-SonicSmart':
                result = process(reading, mode)
                print(result)  # Print JSON output to console for both modes
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON: {line.strip()}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")

def get_table_columns(conn, table_name):
    c = conn.cursor()
    c.execute(f"PRAGMA table_info({table_name})")
    return [column[1] for column in c.fetchall()]

def calculate_bars(percentage):
    thresholds = [0, 15, 25, 35, 45, 55, 65, 75, 85, 95]
    for i, threshold in enumerate(thresholds):
        if percentage <= threshold:
            return max(1, i)
    return 10

@lru_cache(maxsize=1)
def fetch_ppl():
    url = "https://homefuelsdirect.co.uk/home/heating-oil-prices/dorset"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        
        county_table = soup.find("table", id="county-table")
        if county_table:
            price_rows = county_table.find_all("tr")
            if len(price_rows) >= 2:
                price_cells = price_rows[1].find_all("td", class_="trPrice")
                if len(price_cells) >= 2:
                    price_500 = float(price_cells[0].get_text().split()[0])
                    price_900 = float(price_cells[1].get_text().split()[0])
                    return {"500": price_500, "900": price_900}
        
        logger.warning("Unable to find price information in the expected format")
        return None
    except (requests.RequestException, ValueError) as e:
        logger.error(f"Error fetching price: {e}")
        return None

def calculate_ppl(litres, prices):
    if not prices:
        return None
    
    # Linear interpolation between 500L and 900L prices
    if 500 <= litres <= 900:
        price_diff = prices['500'] - prices['900']
        litres_diff = 900 - 500
        price_reduction_per_litre = price_diff / litres_diff
        return prices['500'] - (price_reduction_per_litre * (litres - 500))
    elif litres < 500:
        # For orders less than 500L, use the 500L price
        return prices['500']
    else:
        # For orders over 900L, use the 900L price
        return prices['900']

if __name__ == '__main__':
    main()