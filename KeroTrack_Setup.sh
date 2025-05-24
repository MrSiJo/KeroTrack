#!/bin/bash

# This script is used to setup the KeroTrack Oil Tank Monitoring System on a Debian/Ubuntu LXC or VM.

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
groupadd --system KeroTrack || true
useradd --system --home /opt/KeroTrack --shell /usr/sbin/nologin --gid KeroTrack --comment "KeroTrack service account" KeroTrack || true

# Update system and install required packages
echo "Installing required packages..."
apt-get update
apt-get install -y \
    python3 \
    python3-venv \
    python3-dev \
    python3-pip \
    gcc \
    build-essential \
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
install -d -m 755 /opt/KeroTrack/utils

# Create log files
echo "Setting up log files..."
touch /var/log/KeroTrack-mqtt.log /var/log/KeroTrack-mqtt.err
touch /var/log/KeroTrack-web.log /var/log/KeroTrack-web.err
touch /var/log/KeroTrack-analysis.log /var/log/KeroTrack-analysis.err
touch /var/log/KeroTrack-costanalysis.log /var/log/KeroTrack-costanalysis.err

# Copy files (assuming they're in the current directory)
echo "Copying files..."
# cp config/config.yaml oil_analysis.py oil_recalc.py oil_mqtt_transform.py oil_cost_analysis.py db_connection.py /opt/KeroTrack/
cp -r config/* /opt/KeroTrack/config/
cp -r data/* /opt/KeroTrack/data/
cp -r web/* /opt/KeroTrack/web/
cp -r scripts/* /opt/KeroTrack/scripts/
cp -r utils/* /opt/KeroTrack/utils/

# Update database path in config.yaml to absolute path
sed -i 's|path:.*|path: /opt/KeroTrack/data/KeroTrack_data.db|' /opt/KeroTrack/config/config.yaml

# Fix line endings
echo "Fixing line endings..."
dos2unix /opt/KeroTrack/*.py || true
dos2unix /opt/KeroTrack/config/*.yaml || true
dos2unix /opt/KeroTrack/web/*.py || true
dos2unix /opt/KeroTrack/scripts/*.py || true
dos2unix /opt/KeroTrack/utils/*.py || true

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
    python-dateutil \
    requests \
    beautifulsoup4

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

# Set up weekly analysis cron job
echo "Setting up weekly analysis cron job..."
cat > /etc/cron.weekly/KeroTrack-Analysis << 'EOF'
#!/bin/sh
VENV_PYTHON="/opt/KeroTrack/venv/bin/python3"
export PYTHONPATH="/opt/KeroTrack:${PYTHONPATH}"
cd /opt/KeroTrack
exec $VENV_PYTHON oil_analysis.py >> /var/log/KeroTrack-analysis.log 2>> /var/log/KeroTrack-analysis.err
EOF

# Set up monthly cost analysis cron job
echo "Setting up monthly cost analysis cron job..."
cat > /etc/cron.monthly/KeroTrack-CostAnalysis << 'EOF'
#!/bin/sh
VENV_PYTHON="/opt/KeroTrack/venv/bin/python3"
export PYTHONPATH="/opt/KeroTrack:${PYTHONPATH}"
cd /opt/KeroTrack
exec $VENV_PYTHON oil_cost_analysis.py >> /var/log/KeroTrack-costanalysis.log 2>> /var/log/KeroTrack-costanalysis.err
EOF

# Make files executable
chmod +x /etc/cron.weekly/KeroTrack-Analysis
chmod +x /etc/cron.monthly/KeroTrack-CostAnalysis

# Set correct permissions
echo "Setting permissions..."
chown -R KeroTrack:KeroTrack /opt/KeroTrack
chown KeroTrack:KeroTrack /var/log/KeroTrack-*
chmod -R 755 /opt/KeroTrack
chmod 644 /opt/KeroTrack/config/config.yaml
chmod 644 /var/log/KeroTrack-*

# Copy systemd service files and enable/start services
echo "Setting up systemd services..."
cp KeroTrack-MQTT.service /etc/systemd/system/
cp KeroTrack-Web.service /etc/systemd/system/
dos2unix /etc/systemd/system/KeroTrack-MQTT.service || true
dos2unix /etc/systemd/system/KeroTrack-Web.service || true
systemctl daemon-reload
systemctl enable KeroTrack-MQTT.service
systemctl start KeroTrack-MQTT.service
systemctl enable KeroTrack-Web.service
systemctl start KeroTrack-Web.service

echo "Setup complete!"
echo "Next steps:"
echo "1. Create systemd service files for KeroTrack-MQTT and KeroTrack-Web (see documentation or ask for examples)."
echo "2. Enable and start the services with:"
echo "   sudo systemctl enable KeroTrack-MQTT.service"
echo "   sudo systemctl start KeroTrack-MQTT.service"
echo "   sudo systemctl enable KeroTrack-Web.service"
echo "   sudo systemctl start KeroTrack-Web.service"
echo "3. Check logs in /var/log/KeroTrack-*.log and /var/log/KeroTrack-*.err"
echo "4. Web interface will be available at http://<your-server-ip>:5000" 