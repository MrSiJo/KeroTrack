# KeroTrack - Domestic Heating Oil Monitoring

KeroTrack monitors domestic heating oil (kerosene in the UK) levels by receiving data from a Watchman Sonic ultrasonic transmitter using a LilyGO LoRa32. It's designed to run efficiently inside an Alpine Linux LXC container on Proxmox.

The project is named KeroTrack because it tracks and monitors the kerosene fuel used for central heating and hot water.

## Why

I created this project using Cursor, with no prior experience in Python or Flask.
While I’m new to coding in this language, I have over 20 years of experience in the IT sector, and I love problem-solving and exploring different ways to approach challenges.
Cursor has given me the opportunity to apply my experience in a new way — maybe you could call it vibe coding!

## Overview

The Watchman Sonic transmits data about oil levels in domestic heating oil tanks, the data consists of a depth (in cm) which is from the top of the tank (Where the sensor is) and to the surface of the oil, so it's measuring the air gap it also includes temperature. This data is received by a LilyGO LoRa32 device running OpenMQTTGateway, which publishes the readings to MQTT. The system then processes this data for comprehensive analysis, including consumption forecasting, efficiency tracking, and environmental impact assessment. A web interface provides real-time monitoring and analysis of the oil tank data.

## Features

- Real-time oil level monitoring
- Consumption rate calculation and forecasting
- CO2 emissions estimation
- Heating Degree Days (HDD) calculation
- Seasonal efficiency tracking
- Refill detection
- Leak detection
- Integration with Home Assistant for data visualization
- **Web Interface Features:**
  - Real-time tank status dashboard
  - Historical data visualization
  - Consumption analysis and forecasting
  - Cost analysis and tracking
  - Interactive graphs and charts
  - Mobile-responsive design
  - Dark/Light theme support

## Components

- `oilmqtttransform`: Subscribes to MQTT topics and processes incoming oil level data
- `oil_recalc.py`: Processes oil level data, calculates derived metrics, and updates the database
- `oil_analysis.py`: Performs in-depth analysis on collected data
- `setup-sqlite.py`: Initializes the SQLite database with WAL mode for improved performance
- `config.yaml`: Comprehensive configuration file for system parameters, analysis settings, and hardware specifications
- `db_connection.py`: Implements SQLite connection management with WAL mode support
- `parse_json.py`: Efficient JSON parsing for analysis output
- `web_app.py`: Flask web application for monitoring and analysis interface
- `templates/`: HTML templates for the web interface
- `static/`: Static assets (CSS, JavaScript, images) for the web interface
- `KeroTrack_Setup.sh`: Installation script for setting up the services

## Data Format Examples

### Raw Sensor Data (from LilyGO LoRa32)
```json
{
  "depth_cm": 13,
  "duration": 98000,
  "id": <sensorID>,
  "mic": "CRC",
  "model": "Oil-SonicAdv",
  "protocol": "Watchman Sonic Advanced / Plus",
  "rssi": -49,
  "status": 128,
  "temperature_C": 18
}
```

### Processed Data (from oil_recalc.py / oil_mqtt_transform)
```json
{
  "air_gap_cm": 13.0,
  "bars_remaining": 9,
  "cost_to_fill": "60.62",
  "cost_used": "0.00",
  "current_ppl": 50.99,
  "date": "2025-04-26 14:33:50",
  "heating_degree_days": 0,
  "id": <sensorID>,
  "leak_detected": "n",
  "litres_remaining": 1106.1,
  "litres_to_order": 118.9,
  "litres_used_since_last": 0,
  "oil_depth_cm": 124.0,
  "percentage_remaining": 90.3,
  "raw_flags": 128,
  "refill_detected": "n",
  "seasonal_efficiency": 0.97,
  "temperature": 18.0
}
```

### Analysis Output (from oil_analysis.py)
```json
{
  "avg_daily_consumption_l": 4.4,
  "consumption_per_hdd_l": 0,
  "days_since_refill": 1,
  "estimated_daily_consumption_hdd_l": 1.83,
  "estimated_daily_heating_consumption_l": 0.0,
  "estimated_daily_hot_water_consumption_l": 1.83,
  "estimated_days_remaining": 251.4,
  "estimated_empty_date": "03/01/2026",
  "latest_analysis_date": "2025-04-26 15:15:00",
  "remaining_date_empty_hdd": "21/12/2026",
  "remaining_days_empty_hdd": 604.2,
  "seasonal_heating_factor": 0.04,
  "total_consumption_since_refill": 4.4,
  "upcoming_month_hdd": 0
}
```

## Requirements

### System Requirements
- Alpine Linux LXC container (running on Proxmox)
- LilyGO LoRa32 running OpenMQTTGateway
- Python 3.x
- PyPy3 for improved performance

### Python Packages
- Core packages: `requests`, `beautifulsoup4`, `ujson`, `configparser`, `tqdm`
- Web interface packages: `flask`, `plotly`, `pandas`
- MQTT broker

## Setup and Usage

1. Set up LilyGO LoRa32 with OpenMQTTGateway
2. Configure OpenMQTTGateway to publish to your MQTT broker
3. Install system dependencies and Python packages:
   ```bash
   sudo ./KeroTrack_Setup.sh
   ```
4. Set up the SQLite database:
   ```bash
   python setup-sqlite.py
   ```
5. Configure `config.yaml` with your tank parameters and analysis settings

The system will automatically:
- Monitor the configured MQTT topic for new oil level readings
- Process new readings through `oil_recalc.py`
- Store processed data in the SQLite database
- Perform regular analysis using `oil_analysis.py`
- Serve the web interface on port 5000

### Web Interface Setup

The web interface runs as a system service and starts automatically on boot. To manage the service:

```bash
# Check service status
sudo rc-service KeroTrack-Web status

# Start the service
sudo rc-service KeroTrack-Web start

# Stop the service
sudo rc-service KeroTrack-Web stop

# Restart the service
sudo rc-service KeroTrack-Web restart
```

Access the web interface at:
```
http://<your-server-ip>:5000
```

### MQTT Service Management

The MQTT transformer service processes incoming sensor data and runs as a background service. To manage this service:

```bash
# Check service status
sudo rc-service KeroTrack-MQTT status

# Start the service
sudo rc-service KeroTrack-MQTT start

# Stop the service
sudo rc-service KeroTrack-MQTT stop

# Restart the service
sudo rc-service KeroTrack-MQTT restart
```

### Analysis Job Management

The weekly analysis runs as a cron job. You can manually trigger analysis at any time:

```bash
# Run analysis manually
sudo /etc/periodic/weekly/KeroTrack-Analysis

# View analysis logs
tail -f /var/log/KeroTrack-analysis.log
tail -f /var/log/KeroTrack-analysis.err
```

## Web Interface Features

### Dashboard
- Current oil level with percentage indicator
- Temperature readings
- Estimated days until empty
- Cost analysis including current value and refill costs
- Recent trend visualization

### Historical Data
- Interactive graphs showing oil level trends
- Temperature correlation analysis
- Consumption patterns
- Export capabilities for data analysis

### Analysis
- Detailed consumption analysis
- Cost tracking and forecasting
- Environmental impact assessment
- Seasonal efficiency metrics
- Interactive data visualization

### Settings
- System configuration
- Display preferences
- Analysis parameters
- Theme selection (Dark/Light mode)

## Advanced Features

### Heating Degree Days (HDD)
The system calculates HDD based on the daily average temperature and a configurable base temperature. This helps in understanding heating demand relative to weather conditions.

### Seasonal Efficiency
Tracks the heating system's efficiency across different seasons, allowing for optimization of settings based on weather patterns.

### Refill Detection
Automatically detects when the oil tank has been refilled, providing accurate consumption data and helping to track delivery schedules.

### Leak Detection
The system now includes a leak detection feature to alert users of potential issues with their oil tank or system.

### Performance Optimizations
- Uses SQLite's WAL mode for improved database performance
- Implements connection pooling for efficient database access
- Utilizes PyPy3 for faster Python execution
- Uses `ujson` for faster JSON processing
- Employs efficient data filtering in bash scripts

### Advanced Volume Calculation

The system now uses an improved method for calculating oil volume, taking into account temperature effects and oil density changes:

1. Temperature Correction: 
   - Estimates oil temperature based on ambient temperature and previous readings
   - Accounts for heat transfer through tank walls
   - References: 
```python:python/RTL433 - Domestic Heating Oil/oil_recalc.py
startLine: 193
endLine: 214
```

2. Density Correction:
   - Adjusts oil density based on temperature differences
   - Uses thermal expansion coefficient for more accurate volume estimation
   - References:
```python:python/RTL433 - Domestic Heating Oil/oil_recalc.py
startLine: 215
endLine: 232
```

3. Volume Calculation:
   - Calculates oil mass using temperature-corrected density
   - Converts mass back to volume at reference temperature
   - Provides more accurate readings across varying temperatures

This advanced method improves upon the original linear calculation by accounting for thermal expansion and contraction of the oil, resulting in more accurate volume estimates, especially during temperature fluctuations.

## Data Analysis and Reporting

The system provides comprehensive analysis including:
- Daily and weekly consumption rates
- Projected days until empty
- CO2 emissions based on consumption
- Seasonal efficiency metrics
- Refill frequency and volumes
- Heating Degree Days (HDD) analysis
- Boiler efficiency calculations

## Home Assistant Integration

KeroTrack provides seamless integration with Home Assistant for comprehensive visualization and monitoring of your oil tank data.

### Setup Instructions

1. Copy the provided `ha-oilanalysis.yaml` file to your Home Assistant configuration directory.

2. Add the following line to your Home Assistant `configuration.yaml`:
   ```yaml
   mqtt: !include ha-oilanalysis.yaml
   ```

3. Alternatively, you can directly copy the MQTT sensor configuration from the "Home Assistant Configuration" section below into your existing MQTT configuration.

4. For a rich visualization experience, copy the `lovelace-dashboard.yaml` file to your Home Assistant configuration directory and import it as a new dashboard in the Lovelace UI.

5. Restart Home Assistant to apply the changes.

All KeroTrack metrics will now be available as sensors in your Home Assistant instance, allowing for comprehensive monitoring, alerts, and automation based on your oil tank data.

## Home Assistant Configuration

Add the following configuration to your Home Assistant `configuration.yaml` file to create sensors for all KeroTrack data points:

```yaml
mqtt:
  sensor:
  # oil levels
    - name: "Oil Tank - Temperature"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.temperature }}"
      unit_of_measurement: "°C"

    - name: "Oil Tank - Litres Remaining"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.litres_remaining }}"
      unit_of_measurement: "litres"

    - name: "Oil Tank - Litres Used Since Last"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.litres_used_since_last }}"
      unit_of_measurement: "litres"

    - name: "Oil Tank - Litres to Order"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.litres_to_order }}"
      unit_of_measurement: "litres"

    - name: "Oil Tank - Percentage Remaining"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.percentage_remaining }}"
      unit_of_measurement: "%"

    - name: "Oil Tank - Bars Remaining"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.bars_remaining }}"
      unit_of_measurement: "bars"

    - name: "Oil Tank - Depth"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.oil_depth_cm }}"
      unit_of_measurement: "cm"

    - name: "Oil Tank - Air Gap"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.air_gap_cm }}"
      unit_of_measurement: "cm"

    - name: "Oil Tank - Current Price Per Litre"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.current_ppl }}"
      unit_of_measurement: "pence"

    - name: "Oil Tank - Cost Used"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.cost_used }}"
      unit_of_measurement: "£"

    - name: "Oil Tank - Cost to Fill"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.cost_to_fill }}"
      unit_of_measurement: "£"

    - name: "Oil Tank - Heating Degree Days"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.heating_degree_days }}"
      unit_of_measurement: "HDD"

    - name: "Oil Tank - Seasonal Efficiency"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.seasonal_efficiency }}"
      unit_of_measurement: "%"

    - name: "Oil Tank - Refill Detected"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.refill_detected }}"

    - name: "Oil Tank - Leak Detected"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.leak_detected }}"

    - name: "Oil Tank - Last Update"
      state_topic: "oiltank/level"
      value_template: "{{ value_json.date }}"

  # Oil analysis
    - name: "Oil Tank - Last Analysis Date"
      state_topic: "oiltank/analysis"
      value_template: "{{ value_json.latest_analysis_date }}"

    - name: "Oil Tank - Days Since Refill"
      state_topic: "oiltank/analysis"
      value_template: "{{ value_json.days_since_refill }}"
      unit_of_measurement: "days"

    - name: "Oil Tank - Total Consumption Since Refill"
      state_topic: "oiltank/analysis"
      value_template: "{{ value_json.total_consumption_since_refill }}"
      unit_of_measurement: "L"

    - name: "Oil Tank - Average Daily Consumption"
      state_topic: "oiltank/analysis"
      value_template: "{{ value_json.avg_daily_consumption_l }}"
      unit_of_measurement: "L/day"

    - name: "Oil Tank - Estimated Days Remaining"
      state_topic: "oiltank/analysis"
      value_template: >
        {% set days = value_json.estimated_days_remaining | float %}
        {% if days > 0 %}
          {{ days }}
        {% else %}
          {{ 'Error: ' ~ value_json.estimated_days_remaining }}
        {% endif %}
      unit_of_measurement: "days"

    - name: "Oil Tank - Estimated Empty Date"
      state_topic: "oiltank/analysis"
      value_template: "{{ value_json.estimated_empty_date }}"

    - name: "Oil Tank - Consumption per HDD"
      state_topic: "oiltank/analysis"
      value_template: "{{ value_json.consumption_per_hdd_l }}"
      unit_of_measurement: "L/HDD"

    - name: "Oil Tank - Upcoming Month HDD"
      state_topic: "oiltank/analysis"
      value_template: "{{ value_json.upcoming_month_hdd }}"
      unit_of_measurement: "HDD"

    - name: "Oil Tank - Estimated Daily Consumption (HDD)"
      state_topic: "oiltank/analysis"
      value_template: "{{ value_json.estimated_daily_consumption_hdd_l }}"
      unit_of_measurement: "L/day"

    - name: "Oil Tank - Estimated Daily Hot Water Consumption"
      state_topic: "oiltank/analysis"
      value_template: "{{ value_json.estimated_daily_hot_water_consumption_l }}"
      unit_of_measurement: "L/day"

    - name: "Oil Tank - Estimated Daily Heating Consumption"
      state_topic: "oiltank/analysis"
      value_template: "{{ value_json.estimated_daily_heating_consumption_l }}"
      unit_of_measurement: "L/day"

    - name: "Oil Tank - Seasonal Heating Factor"
      state_topic: "oiltank/analysis"
      value_template: "{{ value_json.seasonal_heating_factor }}"

    - name: "Oil Tank - Remaining Days Until Empty (HDD)"
      state_topic: "oiltank/analysis"
      value_template: "{{ value_json.remaining_days_empty_hdd }}"
      unit_of_measurement: "days"

    - name: "Oil Tank - Estimated Empty Date (HDD)"
      state_topic: "oiltank/analysis"
      value_template: "{{ value_json.remaining_date_empty_hdd }}"
```

After adding this configuration, restart Home Assistant and you'll have access to all KeroTrack data points as sensors in your Home Assistant instance.

### Dashboard Example

You can create a dedicated dashboard for your oil tank monitoring using the Lovelace UI. Here's a simple example:

```yaml
title: Oil Tank Monitoring
views:
  - title: Oil Tank
    cards:
      - type: gauge
        name: Oil Level
        entity: sensor.oil_tank_percentage_remaining
        min: 0
        max: 100
        severity:
          green: 50
          yellow: 25
          red: 10
      
      - type: entities
        title: Current Status
        entities:
          - entity: sensor.oil_tank_temperature
          - entity: sensor.oil_tank_litres_remaining
          - entity: sensor.oil_tank_estimated_days_remaining
          - entity: sensor.oil_tank_estimated_empty_date
          - entity: sensor.oil_tank_cost_to_fill
      
      - type: history-graph
        title: Level History
        entities:
          - entity: sensor.oil_tank_litres_remaining
        hours_to_show: 168
```

## Debugging and Testing

- `fetch_oil_manual.sh` creates a detailed log file, capturing all output including errors. Use this for troubleshooting RTL-SDR or data capture issues.
- `generatetestdata.py` can be used to create synthetic data for testing purposes.
- `processtestdata.py` allows processing of test data for system validation.

### Log Files

All services write to dedicated log files for easier troubleshooting:

- MQTT Service Logs:
  ```bash
  tail -f /var/log/KeroTrack-mqtt.log   # Standard output
  tail -f /var/log/KeroTrack-mqtt.err   # Error output
  ```

- Web Interface Logs:
  ```bash
  tail -f /var/log/KeroTrack-web.log    # Standard output
  tail -f /var/log/KeroTrack-web.err    # Error output
  ```

- Analysis Logs:
  ```bash
  tail -f /var/log/KeroTrack-analysis.log    # Standard output
  tail -f /var/log/KeroTrack-analysis.err    # Error output
  ```

Additional runtime logs are stored in the configured log directory and are rotated according to the retention policy in the configuration file.

## Performance Considerations

This system is optimized for running on a Raspberry Pi 4B. It uses efficient data processing techniques and PyPy3 for improved performance. Regular monitoring of system resources is recommended to ensure smooth operation.

## Configuration

The `config.yaml` file contains comprehensive settings for the oil monitoring system, including:

- Database settings and cleanup parameters
- Logging configurations with retention policies
- Web server settings
- Analysis parameters including CO2 emissions and HDD calculations
- Tank specifications and thermal properties
- Boiler specifications including model, efficiency, and operational parameters
- Detection thresholds for refills and leaks
- Alert configurations
- MQTT broker settings for Home Assistant integration

### Database Configuration
- `path`: Location of SQLite database
- `cleanup_days`: Data retention period in days

### Logging Configuration
- `directory`: Log file location
- `level`: Logging detail level
- `retention_days`: Log file retention period

### Web Configuration
- `secret_key`: Secret key for Flask sessions
- `host`: Host to bind the web server
- `port`: Port for the web interface

### Analysis Parameters
- `co2_per_liter`: CO2 emissions calculation factor
- `hdd_base_temperature`: Base temperature for HDD calculations
- `reference_temperature`: Standard temperature for volume calculations
- `thermal_expansion_coefficient`: Oil thermal expansion factor
- Various thermal and physical properties for accurate calculations

### Tank Specifications
- Detailed physical dimensions
- Thermal properties
- Capacity settings

### Boiler Configuration
- Complete boiler specifications including:
  - Model and burner details
  - Nozzle specifications
  - Fuel consumption rates
  - Efficiency metrics
  - Operational parameters

### Detection Settings
- Configurable thresholds for:
  - Refill detection
  - Leak detection
  - Maximum consumption rates
  - Temperature-based consumption monitoring

### MQTT Integration
- Broker connection details
- Authentication credentials
- Timeout and broadcast intervals

## Fallback Mechanism

The system includes a fallback mechanism to write data to JSON files if the SQLite database is unavailable or if MQTT publishing fails. This ensures data continuity even in case of temporary system issues.

## License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0 International License (CC BY-NC 4.0).  
See the [LICENSE](LICENSE) file for more details.
