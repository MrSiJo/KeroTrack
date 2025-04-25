# KeroTrack - Domestic Heating Oil Monitoring

This project monitors domestic heating oil levels via a Watchman Sonic ultrasonic transmitter, using LoRa communication for data transmission. Optimized for running in an Alpine Linux LXC container on Proxmox.

## Overview

The Watchman Sonic transmits data about oil levels in domestic heating oil tanks. This data is received by a LilyGO LoRa32 device running OpenMQTTGateway, which publishes the readings to MQTT. The system then processes this data for comprehensive analysis, including consumption forecasting, efficiency tracking, and environmental impact assessment. A web interface provides real-time monitoring and analysis of the oil tank data.

## Features

- Real-time oil level monitoring
- Consumption rate calculation and forecasting
- CO2 emissions estimation
- Heating Degree Days (HDD) calculation
- Seasonal efficiency tracking
- Refill detection
- Leak detection
- Integration with Home Assistant for data visualization
- Optimized for Raspberry Pi 4B performance
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
- `config.ini`: Comprehensive configuration file for system parameters, analysis settings, and hardware specifications
- `db_connection.py`: Implements SQLite connection management with WAL mode support
- `parse_json.py`: Efficient JSON parsing for analysis output
- `web_app.py`: Flask web application for monitoring and analysis interface
- `templates/`: HTML templates for the web interface
- `static/`: Static assets (CSS, JavaScript, images) for the web interface
- `install.sh`: Installation script for setting up the web service

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
   sudo ./install.sh
   ```
4. Set up the SQLite database:
   ```bash
   python setup-sqlite.py
   ```
5. Configure `config.ini` with your tank parameters and analysis settings

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
sudo rc-service oil-monitor-web status

# Start the service
sudo rc-service oil-monitor-web start

# Stop the service
sudo rc-service oil-monitor-web stop

# Restart the service
sudo rc-service oil-monitor-web restart
```

Access the web interface at:
```
http://<your-server-ip>:5000
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

Use the provided `ha-oilanalysis.yaml` to set up sensors in Home Assistant for visualizing all analyzed data points, including metrics like HDD, seasonal efficiency, and leak detection.

## Debugging and Testing

- `fetch_oil_manual.sh` creates a detailed log file, capturing all output including errors. Use this for troubleshooting RTL-SDR or data capture issues.
- `generatetestdata.py` can be used to create synthetic data for testing purposes.
- `processtestdata.py` allows processing of test data for system validation.

## Performance Considerations

This system is optimized for running on a Raspberry Pi 4B. It uses efficient data processing techniques and PyPy3 for improved performance. Regular monitoring of system resources is recommended to ensure smooth operation.

## Configuration

The `config.ini` file contains comprehensive settings for the oil monitoring system, including:

- Database settings and cleanup parameters
- Logging configurations with retention policies
- Analysis parameters including CO2 emissions and HDD calculations
- Tank specifications and thermal properties
- Boiler specifications including model, efficiency, and operational parameters
- Detection thresholds for refills and leaks
- MQTT broker settings for Home Assistant integration

### Database Configuration
- `path`: Location of SQLite database
- `cleanup_days`: Data retention period in days

### Logging Configuration
- `directory`: Log file location
- `level`: Logging detail level
- `retention_days`: Log file retention period

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

Licensed under GNU GPL v3.0. Use, modify, and share freely for personal and non-commercial purposes, but keep it open source.

For full license details, see [LICENSE](LICENSE) or visit https://www.gnu.org/licenses/gpl-3.0.en.html.