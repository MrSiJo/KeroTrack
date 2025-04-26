#!/usr/bin/env python3

import paho.mqtt.client as mqtt
from flask import Blueprint, render_template, jsonify
from flask_socketio import SocketIO, emit
import json
import os
import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
import sys

# Ensure the project root is in sys.path before importing utils
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from utils.config_loader import load_config, get_config_value

# Load configuration
config = load_config(os.path.join(project_root, 'config'))

# MQTT Configuration
MQTT_BROKER = get_config_value(config, 'mqtt', 'broker')
MQTT_PORT = get_config_value(config, 'mqtt', 'port')
MQTT_USERNAME = get_config_value(config, 'mqtt', 'username')
MQTT_PASSWORD = get_config_value(config, 'mqtt', 'password')

# MQTT Topics to monitor
MQTT_TOPICS = [(topic['name'], topic['qos']) for topic in get_config_value(config, 'mqtt', 'topics', default=[])]

# Setup logging - use parent directory's logs folder
log_dir = get_config_value(config, 'logging', 'directory', default=os.path.join(project_root, 'logs'))
os.makedirs(log_dir, exist_ok=True)

logger = logging.getLogger('mqtt_viewer')
logger.setLevel(get_config_value(config, 'logging', 'level', default='INFO'))

# Create formatters and handlers
log_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

file_handler = TimedRotatingFileHandler(
    os.path.join(log_dir, 'mqtt_viewer.log'),
    when="midnight",
    interval=1,
    backupCount=get_config_value(config, 'logging', 'retention_days', default=7)
)
file_handler.setFormatter(log_format)
logger.addHandler(file_handler)

# Create Blueprint
mqtt_viewer = Blueprint('mqtt_viewer', __name__)

# Store last message for each topic
topic_messages = {topic: {'timestamp': None, 'payload': None} for topic, _ in MQTT_TOPICS}

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("Connected to MQTT broker")
        for topic, qos in MQTT_TOPICS:
            client.subscribe(topic, qos)
            logger.info(f"Subscribed to {topic}")
    else:
        logger.error(f"Failed to connect to MQTT broker with code {rc}")

def on_message(client, userdata, msg):
    try:
        # Try to parse as JSON
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            payload = msg.payload.decode()

        # Update topic messages
        topic_messages[msg.topic] = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'payload': payload
        }

        # Emit to all connected clients
        socketio.emit('mqtt_message', {
            'topic': msg.topic,
            'timestamp': topic_messages[msg.topic]['timestamp'],
            'payload': payload
        })

        logger.info(f"Received message on topic {msg.topic}")
    except Exception as e:
        logger.error(f"Error processing message: {e}")

# Setup MQTT client
mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

@mqtt_viewer.route('/mqtt')
def index():
    return render_template('mqtt_viewer.html', topics=topic_messages)

@mqtt_viewer.route('/mqtt/messages')
def get_messages():
    return jsonify(topic_messages)

def init_mqtt(app, socketio_instance):
    global socketio
    socketio = socketio_instance
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
    except Exception as e:
        logger.error(f"Failed to start MQTT client: {e}")

    # Register the blueprint
    app.register_blueprint(mqtt_viewer)

    # Register WebSocket event handlers after socketio is set
    @socketio.on('connect', namespace='/ws/kerotrack')
    def handle_connect():
        logger.info("Client connected to WebSocket")
        emit('mqtt_state', topic_messages, namespace='/ws/kerotrack')

    @socketio.on('disconnect', namespace='/ws/kerotrack')
    def handle_disconnect():
        logger.info("Client disconnected from WebSocket") 