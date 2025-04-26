#!/bin/sh

# This script is used to setup the KeroTrack Oil Tank Monitoring System on an Alpine Linux LXC.

# Exit on any error
set -e

# Ensure script is run as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root"
    exit 1
fi

echo "Starting KeroTrack Setup Script..."

# Create KeroTrack user and group
echo "Creating KeroTrack user and group..."
addgroup -S KeroTrack
adduser -S -D -H -h /opt/KeroTrack -s /sbin/nologin -G KeroTrack -g "KeroTrack service account" KeroTrack

# Update system and install required packages
echo "Installing required packages..."
apk update
apk add --no-cache \
    python3 \
    python3-dev \
    py3-pip \
    gcc \
    musl-dev \
    linux-headers \
    sqlite \
    mosquitto-clients \
    dos2unix \
    sudo

# Create service directory
echo "Creating service directory..."
install -d -m 755 /opt/KeroTrack
install -d -m 755 /opt/KeroTrack/web
install -d -m 755 /opt/KeroTrack/data
install -d -m 755 /opt/KeroTrack/config
install -d -m 755 /opt/KeroTrack/scripts

# Create log files
echo "Setting up log files..."
touch /var/log/KeroTrack-mqtt.log /var/log/KeroTrack-mqtt.err
touch /var/log/KeroTrack-web.log /var/log/KeroTrack-web.err
touch /var/log/KeroTrack-analysis.log /var/log/KeroTrack-analysis.err
touch /var/log/KeroTrack-costanalysis.log /var/log/KeroTrack-costanalysis.err

# Copy files (assuming they're in the current directory)
echo "Copying files..."
cp config/config.yaml oil_analysis.py oil_recalc.py oil_mqtt_transform.py oil_cost_analysis.py db_connection.py /opt/KeroTrack/
cp config/* /opt/KeroTrack/config/
cp data/* /opt/KeroTrack/data/
cp -r web/* /opt/KeroTrack/web/
cp -r scripts/* /opt/KeroTrack/scripts/
cp -r utils/* /opt/KeroTrack/utils/

# Fix line endings
echo "Fixing line endings..."
dos2unix /opt/KeroTrack/*.py
dos2unix /opt/KeroTrack/config/*.yaml
dos2unix /opt/KeroTrack/web/*.py
dos2unix /opt/KeroTrack/scripts/*.py
dos2unix /opt/KeroTrack/utils/*.py

# Create and set up virtual environment
echo "Setting up Python virtual environment..."
python3 -m venv /opt/KeroTrack/venv

# Install required Python packages
echo "Installing Python packages..."
/opt/KeroTrack/venv/bin/python3 -m pip install --no-cache-dir \
    Flask==3.0.0 \
    numpy==1.24.3 \
    pandas==1.5.3 \
    plotly==5.18.0 \
    configparser==6.0.0 \
    python-dotenv==1.0.0 \
    paho-mqtt==1.6.1 \
    flask-socketio==5.3.6 \
    eventlet==0.33.3 \
    pyyaml>=6.0.1 \
    python-dateutil

# Create startup scripts
echo "Creating startup scripts..."

# Web Dashboard startup script
cat > /opt/KeroTrack/start-web.sh << 'EOF'
#!/bin/sh
VENV_PYTHON="/opt/KeroTrack/venv/bin/python3"
export PYTHONPATH="/opt/KeroTrack:${PYTHONPATH}"
cd /opt/KeroTrack/web
exec $VENV_PYTHON web_app.py
EOF

# MQTT Transformer startup script
cat > /opt/KeroTrack/start-mqtt.sh << 'EOF'
#!/bin/sh
VENV_PYTHON="/opt/KeroTrack/venv/bin/python3"
export PYTHONPATH="/opt/KeroTrack:${PYTHONPATH}"
cd /opt/KeroTrack
exec $VENV_PYTHON oil_mqtt_transform.py
EOF

chmod +x /opt/KeroTrack/start-*.sh

# Set up MQTT transformer service
echo "Setting up MQTT transformer service..."
cat > /etc/init.d/KeroTrack-MQTT << 'EOF'
#!/sbin/openrc-run

name="KeroTrack-MQTT"
description="KeroTrack MQTT Data Transformer Service"
command="/opt/KeroTrack/start-mqtt.sh"
command_background="yes"
command_user="KeroTrack:KeroTrack"
pidfile="/run/${RC_SVCNAME}.pid"
directory="/opt/KeroTrack"
output_log="/var/log/KeroTrack-mqtt.log"
error_log="/var/log/KeroTrack-mqtt.err"

depend() {
    need net
    after firewall
}
EOF

# Set up web dashboard service
echo "Setting up web dashboard service..."
cat > /etc/init.d/KeroTrack-Web << 'EOF'
#!/sbin/openrc-run

name="KeroTrack-Web"
description="KeroTrack Web Dashboard"
command="/opt/KeroTrack/start-web.sh"
command_background="yes"
command_user="KeroTrack:KeroTrack"
pidfile="/run/${RC_SVCNAME}.pid"
directory="/opt/KeroTrack/web"
output_log="/var/log/KeroTrack-web.log"
error_log="/var/log/KeroTrack-web.err"

depend() {
    need net
    after firewall
}
EOF

# Set up weekly analysis cron job
echo "Setting up weekly analysis cron job..."
cat > /etc/periodic/weekly/KeroTrack-Analysis << 'EOF'
#!/bin/sh
VENV_PYTHON="/opt/KeroTrack/venv/bin/python3"
export PYTHONPATH="/opt/KeroTrack:${PYTHONPATH}"
cd /opt/KeroTrack
exec $VENV_PYTHON oil_analysis.py >> /var/log/KeroTrack-analysis.log 2>> /var/log/KeroTrack-analysis.err
EOF

# Set up monthly cost analysis cron job
echo "Setting up monthly cost analysis cron job..."
cat > /etc/periodic/monthly/KeroTrack-CostAnalysis << 'EOF'
#!/bin/sh
VENV_PYTHON="/opt/KeroTrack/venv/bin/python3"
export PYTHONPATH="/opt/KeroTrack:${PYTHONPATH}"
cd /opt/KeroTrack
exec $VENV_PYTHON oil_cost_analysis.py >> /var/log/KeroTrack-costanalysis.log 2>> /var/log/KeroTrack-costanalysis.err
EOF

# Make files executable
chmod +x /etc/init.d/KeroTrack-*
chmod +x /etc/periodic/weekly/KeroTrack-Analysis
chmod +x /etc/periodic/monthly/KeroTrack-CostAnalysis

# Set correct permissions
echo "Setting permissions..."
chown -R KeroTrack:KeroTrack /opt/KeroTrack
chown KeroTrack:KeroTrack /var/log/KeroTrack-*
chmod -R 755 /opt/KeroTrack
chmod 644 /opt/KeroTrack/config/config.yaml
chmod 644 /var/log/KeroTrack-*

# Enable services
echo "Enabling services..."
rc-update add KeroTrack-MQTT default
rc-update add KeroTrack-Web default
rc-update add crond default

# Start services
echo "Starting services..."
rc-service crond start
rc-service KeroTrack-MQTT start
rc-service KeroTrack-Web start

echo "Setup complete! Checking service status..."
rc-service KeroTrack-MQTT status
rc-service KeroTrack-Web status

# Get the primary IP address for web interface
WEB_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '^127\.' | grep -v '^172\.' | grep -v '^10\.' | head -n1)

echo """
Installation completed successfully!

KeroTrack components:
1. MQTT Transformer Service (KeroTrack-MQTT)
   - Handles real-time data transformation
   - Status: rc-service KeroTrack-MQTT status
   - Logs: tail -f /var/log/KeroTrack-mqtt.{log,err}

2. Web Dashboard (KeroTrack-Web)
   - Provides web interface at http://${WEB_IP}:5000
   - Status: rc-service KeroTrack-Web status
   - Logs: tail -f /var/log/KeroTrack-web.{log,err}

3. Weekly Analysis (cron job)
   - Runs every week automatically
   - Logs: tail -f /var/log/KeroTrack-analysis.{log,err}

4. Monthly Cost Analysis (cron job)
   - Runs monthly automatically
   - Logs: tail -f /var/log/KeroTrack-costanalysis.{log,err}

All services are now configured and running.
""" 