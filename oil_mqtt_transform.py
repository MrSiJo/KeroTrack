#!/usr/bin/env python3

"""
This script transforms raw MQTT messages from the Watchman Sonic Advanced oil tank sensor
into a standardized format for the oil monitoring system.
"""

import sqlite3
import os
import sys
import json
import logging
from datetime import datetime, timedelta
import paho.mqtt.client as mqtt
from utils.config_loader import load_config, get_config_value
import argparse
import time
from logging.handlers import TimedRotatingFileHandler
from oil_recalc import process
from db_connection import get_db_connection

# Load configuration
config = load_config()

# Set up logging
log_dir = get_config_value(config, 'logging', 'directory', default="logs")
os.makedirs(log_dir, exist_ok=True)
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = os.path.join(log_dir, f"oil_mqtt_transform_{timestamp}.log")

logger = logging.getLogger(__name__)
logger.setLevel(get_config_value(config, 'logging', 'level', default="INFO"))

# Clear existing handlers
logger.handlers = []

# Create handlers
file_handler = TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=get_config_value(config, 'logging', 'retention_days', default=7))
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
DB_PATH = get_config_value(config, 'database', 'path')

# MQTT Configuration
MQTT_BROKER = get_config_value(config, 'mqtt', 'broker')
MQTT_PORT = get_config_value(config, 'mqtt', 'port')
MQTT_USERNAME = get_config_value(config, 'mqtt', 'username')
MQTT_PASSWORD = get_config_value(config, 'mqtt', 'password')
MQTT_TIMEOUT = get_config_value(config, 'mqtt', 'timeout_minutes')
MQTT_BROADCAST_INTERVAL = get_config_value(config, 'mqtt', 'broadcast_interval_minutes')

# Get topics from config
SUBSCRIBE_TOPIC = next(topic['name'] for topic in get_config_value(config, 'mqtt', 'topics') 
                      if 'RTL_433toMQTT' in topic['name'])

def get_topic_by_name(topics, logical_name):
    return next(topic['topicname'] for topic in topics if topic['name'] == logical_name)

topics = get_config_value(config, 'mqtt', 'topics')
PUBLISH_LEVEL_TOPIC = get_topic_by_name(topics, "KTreadings")
PUBLISH_ANALYSIS_TOPIC = get_topic_by_name(topics, "KTanalytics")

# Default timeout for one-shot mode (35 minutes unless specified in config)
DEFAULT_TIMEOUT = MQTT_TIMEOUT * 60 if MQTT_TIMEOUT else 35 * 60  # 35 minutes default timeout for one-shot mode

def on_connect(client, userdata, flags, rc):
    logger.info(f"Connected to MQTT broker with result code {rc}")
    client.subscribe(SUBSCRIBE_TOPIC)
    logger.info(f"Subscribed to {SUBSCRIBE_TOPIC}")

def on_message(client, userdata, msg):
    try:
        # Parse incoming message
        payload = json.loads(msg.payload.decode())
        logger.info(f"Received MQTT message on {msg.topic}:")
        logger.info(f"Input payload: {json.dumps(payload, indent=2)}")

        # Transform model name to match expected format
        if payload['model'] == 'Oil-SonicAdv':
            payload['model'] = 'Oil-SonicSmart'
            
        # Add timestamp if not present
        if 'time' not in payload:
            payload['time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Process data using existing oil_recalc logic
        processed_data = process(payload, "sqlite")
        
        if processed_data:
            # Convert processed_data back to dict if it's a JSON string
            try:
                data_dict = json.loads(processed_data) if isinstance(processed_data, str) else processed_data
            except json.JSONDecodeError:
                logger.error("Failed to parse processed data as JSON")
                return

            # Store in database using db_connection
            try:
                with get_db_connection(DB_PATH) as conn:
                    cursor = conn.cursor()
                    
                    # Get column names from the readings table
                    cursor.execute("PRAGMA table_info(readings)")
                    columns = [column[1] for column in cursor.fetchall()]
                    
                    # Filter data_dict to match table columns
                    filtered_data = {k: v for k, v in data_dict.items() if k in columns}
                    
                    # Prepare SQL statement
                    columns_str = ', '.join(filtered_data.keys())
                    placeholders = ', '.join(['?' for _ in filtered_data])
                    sql = f"INSERT INTO readings ({columns_str}) VALUES ({placeholders})"
                    
                    # Execute insert
                    cursor.execute(sql, list(filtered_data.values()))
                    conn.commit()
                    logger.info(f"Successfully stored reading in database with timestamp: {data_dict.get('date')}")
            except Exception as db_error:
                logger.error(f"Database error: {db_error}", exc_info=True)
        
        # Publish processed data
        client.publish(PUBLISH_LEVEL_TOPIC, processed_data, retain=True)
        logger.info(f"Published to {PUBLISH_LEVEL_TOPIC}:")
        logger.info(f"Output payload: {processed_data}")
        
        # If in one-shot mode, set the message received flag
        if userdata.get('one_shot'):
            logger.debug("One-shot mode: Setting message_received flag")
            userdata['message_received'] = True
            
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        if userdata.get('one_shot'):
            userdata['message_received'] = True

def main():
    parser = argparse.ArgumentParser(description="Process oil tank readings")
    parser.add_argument("--mode", choices=["sqlite", "json"], default="sqlite",
                        help="Output mode: sqlite (default) or json")
    parser.add_argument("--oneshot", action="store_true",
                        help="Run in one-shot mode instead of continuous mode")
    args = parser.parse_args()

    client = mqtt.Client(userdata={'one_shot': args.oneshot, 'message_received': False})
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        
        if args.oneshot:
            # One-shot mode
            logger.info(f"Starting one-shot MQTT read (timeout: {DEFAULT_TIMEOUT/60:.0f} minutes)...")
            client.loop_start()
            
            # Add a small delay to ensure connection is established
            time.sleep(0.5)
            
            # Wait for message
            timeout = DEFAULT_TIMEOUT
            logger.info("Waiting for message...")
            while timeout > 0 and client.is_connected() and not client._userdata['message_received']:
                if timeout % 60 == 0:  # Log every minute
                    logger.info(f"Still waiting... {timeout/60:.0f} minutes remaining")
                time.sleep(1)
                timeout -= 1
            
            client.loop_stop()
            
            if timeout == 0:
                logger.error(f"Timeout waiting for message after {DEFAULT_TIMEOUT/60:.0f} minutes")
                sys.exit(1)
            elif client._userdata['message_received']:
                logger.info("Message received and processed successfully")
                sys.exit(0)
            else:
                logger.error("Unexpected exit from wait loop")
                sys.exit(1)
        else:
            # Continuous mode (now default)
            logger.info("Starting continuous MQTT monitoring...")
            logger.info("Expecting readings approximately every 30 minutes")
            
            # Add last message timestamp tracking
            last_message_time = datetime.now()
            
            def check_connection():
                nonlocal last_message_time
                current_time = datetime.now()
                time_since_last = (current_time - last_message_time).total_seconds() / 60
                
                if time_since_last > 45:  # Alert if no message for 45 minutes
                    logger.warning(f"No messages received for {time_since_last:.1f} minutes")
                
            # Update on_message to track last message time
            def wrapped_on_message(client, userdata, msg):
                nonlocal last_message_time
                last_message_time = datetime.now()
                on_message(client, userdata, msg)
            
            client.on_message = wrapped_on_message
            
            # Start the MQTT loop
            client.loop_start()
            
            try:
                while True:
                    check_connection()
                    time.sleep(300)  # Check every 5 minutes
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt, shutting down...")
                client.loop_stop()
                sys.exit(0)
                
    except Exception as e:
        logger.error(f"Error in main loop: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
