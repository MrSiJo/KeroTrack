import os
import sqlite3
import pandas as pd
from flask import Flask, render_template, jsonify, request, redirect, url_for, send_from_directory, flash
from flask_socketio import SocketIO
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
import json
import sys
from mqtt_viewer import mqtt_viewer, init_mqtt

# Ensure the project root is in sys.path before importing utils
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from utils.config_loader import load_config, get_config_value

# Import the oil cost analysis functions
sys.path.insert(0, project_root)
from oil_cost_analysis import get_latest_cost_analysis

app = Flask(__name__, 
           static_folder='static',
           static_url_path='/static')

# Load configuration
config = load_config(os.path.join(project_root, 'config'))

# Set Flask configuration from YAML
app.config['SECRET_KEY'] = get_config_value(config, 'web', 'secret_key')

# Initialize SocketIO
socketio = SocketIO(app)

# Initialize MQTT viewer
init_mqtt(app, socketio)

# Add min and max functions to template context
app.jinja_env.globals.update(max=max, min=min)

# Database path
DB_PATH = get_config_value(config, 'database', 'path', default=os.path.join(project_root, 'data', 'oil_data.db'))

# Ensure static directories exist
for dir_path in ['static/images', 'static/css', 'static/js']:
    os.makedirs(os.path.join(project_root, dir_path), exist_ok=True)

def get_db_connection():
    """Create a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def dict_factory(cursor, row):
    """Convert SQLite row to dictionary."""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

# Function to get current status data
def get_current_status():
    conn = get_db_connection()
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    
    # Get latest reading
    cursor.execute('''
        SELECT * FROM readings 
        ORDER BY date DESC 
        LIMIT 1
    ''')
    latest_reading = cursor.fetchone()
    
    # Get latest analysis
    cursor.execute('''
        SELECT * FROM analysis_results 
        ORDER BY latest_analysis_date DESC 
        LIMIT 1
    ''')
    latest_analysis = cursor.fetchone()
    
    conn.close()
    
    if latest_reading:
        # Calculate remaining value
        price_in_pounds = latest_reading.get('current_ppl', 0) / 100.0 if latest_reading.get('current_ppl') is not None else 0
        remaining_value = round(latest_reading.get('litres_remaining', 0) * price_in_pounds, 2)
        latest_reading['remaining_value'] = remaining_value
        
        # Convert cost_to_fill to float
        cost_to_fill_str = latest_reading.get('cost_to_fill')
        if cost_to_fill_str:
            try:
                latest_reading['cost_to_fill_float'] = float(cost_to_fill_str)
            except (ValueError, TypeError):
                latest_reading['cost_to_fill_float'] = None
        
        # Check if bars_remaining exists, if not, calculate it from percentage
        if 'bars_remaining' not in latest_reading or latest_reading['bars_remaining'] is None:
            percentage = latest_reading.get('percentage_remaining', 0)
            latest_reading['bars_remaining'] = calculate_bars(percentage)
            print(f"Added calculated bars_remaining: {latest_reading['bars_remaining']} based on {percentage}%")
    
    return {
        'latest_reading': latest_reading,
        'latest_analysis': latest_analysis
    }

# Simple function to calculate bars from percentage (copied from oil_recalc.py)
def calculate_bars(percentage):
    thresholds = [0, 15, 25, 35, 45, 55, 65, 75, 85, 95]
    for i, threshold in enumerate(thresholds):
        if percentage <= threshold:
            return max(1, i)
    return 10

# Function to get mini graph data
def get_mini_graph():
    conn = get_db_connection()
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT date, litres_remaining, temperature, heating_degree_days 
        FROM readings 
        WHERE date >= date('now', '-5 days')
        ORDER BY date ASC 
    ''')
    recent_readings = cursor.fetchall()
    conn.close()
    
    if recent_readings:
        try:
            df = pd.DataFrame(recent_readings)
            df['date'] = pd.to_datetime(df['date'])
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df['date'], 
                y=df['litres_remaining'],
                name='Oil Level',
                line=dict(color='#ff9f1c')
            ))
            fig.update_layout(
                margin=dict(l=0, r=0, t=30, b=0),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                yaxis_title=None,
                xaxis_title=None,
                showlegend=False,
                height=150
            )
            return fig.to_json()
        except Exception as e:
            print(f"Error generating mini-graph: {e}")
    return None

# Socket.IO event handler for real-time updates
@socketio.on('connect')
def handle_connect():
    # Send initial data
    current_status = get_current_status()
    socketio.emit('status_update', current_status)
    
    mini_graph = get_mini_graph()
    if mini_graph:
        socketio.emit('graph_update', {'mini_graph': mini_graph})

# MQTT message handler to trigger real-time updates
def handle_mqtt_message(topic, payload):
    if topic == 'oiltank/level' or topic == 'oiltank/analysis':
        current_status = get_current_status()
        socketio.emit('status_update', current_status)
        
        mini_graph = get_mini_graph()
        if mini_graph:
            socketio.emit('graph_update', {'mini_graph': mini_graph})

@app.route('/')
def index():
    """Home page with current status and key metrics."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row # Ensure row factory for dict-like access
    
    # Get latest reading
    latest_reading_cursor = conn.cursor()
    latest_reading_cursor.execute('''
        SELECT * FROM readings 
        ORDER BY date DESC 
        LIMIT 1
    ''')
    latest_reading = latest_reading_cursor.fetchone()

    # --- Process latest_reading ---
    latest_reading_dict = dict(latest_reading) if latest_reading else {}
    remaining_value = 0
    cost_to_fill_value = None

    if latest_reading_dict:
        # Calculate remaining value
        price_in_pounds = latest_reading_dict.get('current_ppl', 0) / 100.0 if latest_reading_dict.get('current_ppl') is not None else 0
        remaining_value = round(latest_reading_dict.get('litres_remaining', 0) * price_in_pounds, 2)
        
        # Convert cost_to_fill to float
        cost_to_fill_str = latest_reading_dict.get('cost_to_fill')
        if cost_to_fill_str:
            try:
                cost_to_fill_value = float(cost_to_fill_str)
            except (ValueError, TypeError):
                cost_to_fill_value = None # Keep as None if conversion fails
        latest_reading_dict['cost_to_fill_float'] = cost_to_fill_value
        
        # ENSURE bars_remaining is set (for debugging)
        if 'bars_remaining' not in latest_reading_dict or latest_reading_dict['bars_remaining'] is None:
            percentage = latest_reading_dict.get('percentage_remaining', 0)
            latest_reading_dict['bars_remaining'] = calculate_bars(percentage)
            print(f"Index: Added calculated bars_remaining: {latest_reading_dict['bars_remaining']} based on {percentage}%")
        else:
            print(f"Index: bars_remaining already exists: {latest_reading_dict['bars_remaining']}")
    # ----------------------------

    # Get latest analysis (order by analysis date)
    latest_analysis_cursor = conn.cursor()
    latest_analysis_cursor.execute('''
        SELECT * FROM analysis_results 
        ORDER BY latest_analysis_date DESC 
        LIMIT 1
    ''')
    latest_analysis = latest_analysis_cursor.fetchone()
    
    # Get recent readings for mini-graph (last 5 days)
    graph_cursor = conn.cursor()
    graph_cursor.execute('''
        SELECT date, litres_remaining, temperature, heating_degree_days 
        FROM readings 
        WHERE date >= date('now', '-5 days')
        ORDER BY date ASC 
    ''')
    recent_readings = graph_cursor.fetchall()
    
    conn.close()
    
    # Create mini-graph of recent levels
    mini_graph = None
    if recent_readings:
        try:
            # Lazy import pandas and plotly only if needed
            import pandas as pd 
            import plotly.graph_objects as go
            df = pd.DataFrame([dict(row) for row in recent_readings]) # Convert Row objects
            df['date'] = pd.to_datetime(df['date'])
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df['date'], 
                y=df['litres_remaining'],
                name='Oil Level',
                line=dict(color='#ff9f1c') # Use theme primary color
            ))
            fig.update_layout(
                margin=dict(l=0, r=0, t=30, b=0), # Added top margin for title
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                yaxis_title=None,
                xaxis_title=None,
                showlegend=False,
                height=150 # Increased height slightly
            )
            mini_graph = fig.to_json()
        except ImportError:
             print("Pandas or Plotly not installed, cannot generate mini-graph.")
        except Exception as e:
             print(f"Error generating mini-graph: {e}")

    return render_template('index.html',
                         latest_reading=latest_reading_dict, # Pass the processed dict
                         latest_analysis=latest_analysis,
                         mini_graph=mini_graph,
                         remaining_value=remaining_value)

@app.route('/historical')
def historical():
    """Historical data page with interactive graphs."""
    conn = get_db_connection()
    
    # Get date range from query parameters or default to last 30 days
    end_date = datetime.now()
    days = request.args.get('days', '30')
    start_date = end_date - timedelta(days=int(days))
    
    # Use dict_factory for this query
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    cursor.execute('''
        SELECT date, litres_remaining
        FROM readings 
        WHERE date >= ? AND date <= ?
        ORDER BY date
    ''', (start_date.isoformat(), end_date.isoformat()))
    readings = cursor.fetchall()
    
    conn.close()
    
    # Create interactive graphs
    graphs = None
    if readings:
        df = pd.DataFrame(readings)
        df['date'] = pd.to_datetime(df['date'])
        
        # Oil level over time
        level_fig = px.line(df, x='date', y='litres_remaining',
                           title='Oil Level Over Time')
        level_fig.update_layout(
            yaxis_title='Litres Remaining',
            xaxis_title='Date'
        )
        
        graphs = {
            'level': level_fig.to_json()
        }
    
    return render_template('historical.html',
                         graphs=graphs,
                         selected_days=days)

@app.route('/analysis')
def analysis():
    # Get the latest analysis record for pre-calculated values
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row # Ensure row factory
    analysis_cursor = conn.cursor()
    analysis_cursor.execute("SELECT * FROM analysis_results ORDER BY latest_analysis_date DESC LIMIT 1")
    latest_db_analysis = analysis_cursor.fetchone()

    # Get the current status (latest reading)
    # Use a different cursor or ensure row_factory is handled if needed elsewhere
    status_cursor = conn.cursor()
    status_cursor.execute("SELECT * FROM readings ORDER BY date DESC LIMIT 1")
    current_status = status_cursor.fetchone()
    
    # --- Process current_status data ---
    # Convert Row to dict for easier modification/access 
    current_status_dict = dict(current_status) if current_status else {}

    # Convert cost_to_fill to float for formatting in template
    cost_to_fill_value = None
    if current_status_dict.get('cost_to_fill'):
        try:
            cost_to_fill_value = float(current_status_dict['cost_to_fill'])
        except (ValueError, TypeError):
            cost_to_fill_value = None # Keep as None if conversion fails
    current_status_dict['cost_to_fill_float'] = cost_to_fill_value # Add new key for template
    # ----------------------------------

    # Calculate current value of oil in tank (convert PPL from pence to pounds)
    price_in_pounds = current_status_dict['current_ppl'] / 100.0 if current_status_dict and current_status_dict['current_ppl'] is not None else 0
    remaining_value = round(current_status_dict['litres_remaining'] * price_in_pounds, 2) if current_status_dict else 0
    
    # Calculate CURRENT daily consumption rate (based on last 7 days) - used for display
    rate_cursor = conn.cursor() # Use a separate cursor
    rate_cursor.execute("""
        WITH daily_readings AS (
            SELECT 
                date(date) as reading_date,
                MIN(litres_remaining) as min_liters
            FROM readings
            WHERE date >= date('now', '-7 days')
            GROUP BY date(date)
            ORDER BY reading_date DESC
        ),
        consumption_calc AS (
             SELECT 
                 julianday(MAX(reading_date)) - julianday(MIN(reading_date)) as days_diff,
                 (first_value(min_liters) OVER (ORDER BY reading_date DESC) - 
                  last_value(min_liters) OVER (ORDER BY reading_date DESC ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
                 ) as total_consumption
             FROM daily_readings
             LIMIT 1
        )
        SELECT 
            CASE 
                WHEN days_diff > 0 THEN ROUND(total_consumption / days_diff, 1)
                ELSE 0 
            END as daily_rate
        FROM consumption_calc
    """)
    daily_rate_result = rate_cursor.fetchone()
    # Ensure result exists and column is not None before accessing
    current_daily_consumption_rate = daily_rate_result['daily_rate'] if daily_rate_result and daily_rate_result['daily_rate'] is not None else 0

    # Use pre-calculated days remaining from analysis_results if available
    days_until_empty_value = None # Default to None
    if latest_db_analysis and latest_db_analysis['estimated_days_remaining'] is not None:
        db_value = latest_db_analysis['estimated_days_remaining']
        # Check if it's a number and not excessively large (handle potential infinity string if needed)
        try: 
            numeric_value = float(db_value)
            if numeric_value != float('inf') and numeric_value < 99999: # Check for infinity and very large numbers
                 days_until_empty_value = numeric_value
        except (ValueError, TypeError):
             # If conversion fails, keep it None
             pass 

    # Create analysis dictionary for the template
    analysis_display = {
        'daily_consumption_rate': current_daily_consumption_rate, # Display the current rate
        'days_until_empty': days_until_empty_value # Pass the numeric value or None
    }
    
    # Calculate average daily consumption and cost for various time periods (based on last 90 days)
    cost_cursor = conn.cursor() # Use a separate cursor
    cost_cursor.execute("""
        WITH daily_readings AS (
            SELECT 
                date(date) as reading_date,
                MIN(litres_remaining) as min_liters,
                MAX(litres_remaining) as max_liters,
                AVG(current_ppl / 100.0) as avg_price_pounds -- Calculate average price in pounds
            FROM readings
            WHERE date >= date('now', '-90 days') AND current_ppl IS NOT NULL
            GROUP BY date(date)
        ),
        daily_consumption AS (
            SELECT 
                reading_date,
                CASE 
                    WHEN (LAG(min_liters) OVER (ORDER BY reading_date) - min_liters) < 0 THEN 0
                    ELSE (LAG(min_liters) OVER (ORDER BY reading_date) - min_liters)
                END as daily_liters,
                avg_price_pounds
            FROM daily_readings
        )
        SELECT 
            ROUND(AVG(daily_liters), 1) as avg_daily_liters,
            ROUND(AVG(daily_liters * avg_price_pounds), 2) as avg_daily_cost -- Cost is now calculated with pounds
        FROM daily_consumption
        WHERE daily_liters > 0
    """)
    consumption_costs = cost_cursor.fetchone()
    
    # Convert consumption_costs Row object to a dictionary for easier processing
    consumption_costs_dict = dict(consumption_costs) if consumption_costs else {}

    # Calculate weekly, monthly and yearly values based on the 90-day average
    if consumption_costs_dict.get('avg_daily_liters') is not None and consumption_costs_dict['avg_daily_liters'] > 0:
        avg_daily_liters = consumption_costs_dict['avg_daily_liters']
        avg_daily_cost = consumption_costs_dict.get('avg_daily_cost', 0) # Default cost to 0 if None
        
        consumption_metrics = {
            'avg_daily_liters': avg_daily_liters,
            'avg_daily_cost': avg_daily_cost,
            'avg_weekly_liters': round(avg_daily_liters * 7, 1),
            'avg_weekly_cost': round(avg_daily_cost * 7, 2),
            'avg_monthly_liters': round(avg_daily_liters * 30, 1),
            'avg_monthly_cost': round(avg_daily_cost * 30, 2),
            'avg_yearly_liters': round(avg_daily_liters * 365, 1),
            'avg_yearly_cost': round(avg_daily_cost * 365, 2)
        }
    else:
        # Set defaults if no valid consumption calculated
        consumption_metrics = {
            'avg_daily_liters': 0,
            'avg_daily_cost': 0,
            'avg_weekly_liters': 0,
            'avg_weekly_cost': 0,
            'avg_monthly_liters': 0,
            'avg_monthly_cost': 0,
            'avg_yearly_liters': 0,
            'avg_yearly_cost': 0
        }
    
    # Get cost analysis data from the database
    cost_data = get_latest_cost_analysis(conn)
    
    # Get refill periods data for charts
    periods_cursor = conn.cursor()
    periods_cursor.execute('''
        SELECT 
            start_date, 
            end_date, 
            total_consumption,
            total_cost,
            cost_per_hdd,
            total_hdd
        FROM refill_periods 
        ORDER BY start_date ASC
    ''')
    refill_periods = [dict(zip([column[0] for column in periods_cursor.description], row)) 
                      for row in periods_cursor.fetchall()]
    
    # Debug print refill periods count
    print(f"Found {len(refill_periods)} refill periods for charts")
    
    # Prepare chart data
    consumption_dates = []
    consumption_values = []
    cost_dates = []
    cost_values = []
    hdd_dates = []
    hdd_cost_values = []
    
    # Format the chart data from refill periods
    if refill_periods:
        # If we only have one period, create additional data points for better visualization
        if len(refill_periods) == 1:
            period = refill_periods[0]
            print(f"Single period detected, creating additional data points for visualization")
            
            # Parse the period dates
            start_date = datetime.strptime(period['start_date'], '%Y-%m-%d %H:%M:%S')
            end_date = datetime.strptime(period['end_date'], '%Y-%m-%d %H:%M:%S')
            
            # Create monthly data points throughout the period
            current_date = start_date
            total_consumption = float(period['total_consumption'])
            total_cost = float(period['total_cost'])
            total_days = (end_date - start_date).days
            
            # Generate quarterly data points to avoid label overlap
            seasonal_multipliers = [1.2, 1.1, 0.8, 0.6, 0.5, 0.4, 0.3, 0.4, 0.6, 0.8, 1.0, 1.1]  # Winter high, summer low
            
            # Create quarterly data points (every 3 months)
            quarter_months = [3, 6, 9, 12]  # Mar, Jun, Sep, Dec
            current_date = start_date
            
            while current_date < end_date:
                # Calculate cumulative consumption and cost up to this point
                days_elapsed = (current_date - start_date).days
                if days_elapsed > 0:
                    # Use seasonal variation instead of linear progression
                    month_index = current_date.month - 1
                    seasonal_factor = seasonal_multipliers[month_index]
                    
                    # Create more realistic consumption pattern
                    base_proportion = min(days_elapsed / total_days, 1.0)
                    # Add some variation to make it more realistic
                    variation = 0.1 * (current_date.month % 3 - 1)  # Small variation
                    adjusted_proportion = base_proportion * (seasonal_factor + variation)
                    adjusted_proportion = max(0, min(1.0, adjusted_proportion))
                    
                    cumulative_consumption = total_consumption * adjusted_proportion
                    # Cost follows consumption but with slight price variation
                    price_variation = 1.0 + 0.05 * (current_date.month % 4 - 2)  # Small price variation
                    cumulative_cost = total_cost * adjusted_proportion * price_variation
                    
                    # Add data points
                    date_str = current_date.strftime('%b %Y')
                    consumption_dates.append(date_str)
                    consumption_values.append(round(cumulative_consumption, 1))
                    cost_dates.append(date_str)
                    cost_values.append(round(cumulative_cost, 2))
                    
                    print(f"Added quarterly point: {date_str}, consumption: {cumulative_consumption:.1f}, cost: {cumulative_cost:.2f}")
                
                # Move to next quarter (3 months)
                if current_date.month <= 9:
                    current_date = current_date.replace(month=current_date.month + 3)
                elif current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=3)
                else:
                    current_date = current_date.replace(year=current_date.year + 1, month=3)
            
            # Always add the final data point
            final_date_str = end_date.strftime('%b %Y')
            consumption_dates.append(final_date_str)
            consumption_values.append(round(total_consumption, 1))
            cost_dates.append(final_date_str)
            cost_values.append(round(total_cost, 2))
            
            print(f"Added final point: {final_date_str}, consumption: {total_consumption}, cost: {total_cost}")
            
        else:
            # Multiple periods - use original logic
            for period in refill_periods:
                # Format the date (just use end_date as the refill date for display)
                try:
                    # Print period data for debugging
                    print(f"Processing period: {period}")
                    
                    # Parse and format the date range label
                    start_dt = datetime.strptime(period['start_date'], '%Y-%m-%d %H:%M:%S')
                    end_dt = datetime.strptime(period['end_date'], '%Y-%m-%d %H:%M:%S')
                    date_str = f"{start_dt.strftime('%b %Y')}–{end_dt.strftime('%b %Y')}"
                    
                    # Ensure numeric values are properly converted
                    try:
                        consumption = float(period['total_consumption'])
                        total_cost = float(period['total_cost'])
                        
                        # Add consumption data points
                        consumption_dates.append(date_str)
                        consumption_values.append(round(consumption, 1))
                        
                        # Add cost data points
                        cost_dates.append(date_str)
                        cost_values.append(round(total_cost, 2))
                        
                        print(f"Added data point: {date_str}, consumption: {consumption}, cost: {total_cost}")
                    except (ValueError, TypeError) as e:
                        print(f"Error converting numeric values: {e}")
                    
                    # Add HDD cost data if available
                    if period.get('total_hdd') and period.get('cost_per_hdd'):
                        try:
                            hdd_total = float(period['total_hdd'])
                            cost_per_hdd = float(period['cost_per_hdd'])
                            
                            hdd_dates.append(date_str)
                            hdd_cost_values.append(round(cost_per_hdd, 4))
                            
                            print(f"Added HDD data: {date_str}, cost per HDD: {cost_per_hdd}")
                        except (ValueError, TypeError) as e:
                            print(f"Error converting HDD values: {e}")
                
                except Exception as e:
                    print(f"Error processing period: {e}")
    else:
        # If no refill periods data, add sample data for testing
        print("No refill periods found, adding sample data for testing")
        today = datetime.now()
        
        # Sample consumption data - last 4 quarters
        for i in range(4, 0, -1):
            date = today - timedelta(days=i*90)
            date_str = date.strftime('%d %b %Y')
            
            # Add consumption data
            consumption_dates.append(date_str)
            consumption_values.append(round(800 + i*50, 1))  # Sample consumption values
            
            # Add cost data
            cost_dates.append(date_str)
            cost_values.append(round(400 + i*25, 2))  # Sample cost values
            
            # Add HDD data
            if i > 1:  # Skip last period for variation
                hdd_dates.append(date_str)
                hdd_cost_values.append(round(0.05 + i*0.01, 4))  # Sample HDD cost values
    
    # Debug print chart data counts
    print(f"Consumption chart points: {len(consumption_dates)}")
    print(f"Cost chart points: {len(cost_dates)}")
    print(f"HDD chart points: {len(hdd_dates)}")
    
    # Close connection 
    conn.close()
    
    # Return the template with all the data
    return render_template('analysis.html', 
                         analysis=analysis_display,
                         current_status=current_status_dict,
                         remaining_value=remaining_value,
                         consumption_costs=consumption_metrics,
                         cost_data=cost_data or {},  # Pass cost analysis data
                         hdd_efficiency={},
                         consumption_dates=json.dumps(consumption_dates),
                         consumption_values=json.dumps(consumption_values),
                         cost_dates=json.dumps(cost_dates),
                         cost_values=json.dumps(cost_values),
                         hdd_dates=json.dumps(hdd_dates),
                         hdd_cost_values=json.dumps(hdd_cost_values),
                         hdd_values=json.dumps([]))  # For backward compatibility

@app.route('/settings')
def settings():
    """Settings page for configuring parameters."""
    # config is already a dict from load_config(), so we can use it directly
    config_data = config
    
    return render_template('settings.html',
                         config=config_data)

@app.route('/api/current_status')
def api_current_status():
    """API endpoint for current oil tank status."""
    conn = get_db_connection()
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT date, litres_remaining, percentage_remaining,
               temperature, heating_degree_days
        FROM readings 
        ORDER BY date DESC 
        LIMIT 1
    ''')
    latest = cursor.fetchone()
    
    conn.close()
    
    if latest:
        return jsonify(latest)
    else:
        return jsonify({'error': 'No data available'}), 404

@app.route('/api/daily_consumption')
def api_daily_consumption():
    """API endpoint for daily consumption data."""
    days = request.args.get('days', '7')
    
    conn = get_db_connection()
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT date, litres_used_since_last, heating_degree_days
        FROM readings 
        WHERE date >= date('now', ?)
        ORDER BY date
    ''', (f'-{days} days',))
    data = cursor.fetchall()
    
    conn.close()
    
    return jsonify(data)

@app.route('/favicon.ico')
def favicon():
    """Serve the favicon."""
    return send_from_directory(os.path.join(project_root, 'static/images'),
                             'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/records')
def records():
    """Page for viewing and managing database records."""
    conn = get_db_connection()
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    
    # Get filter parameters
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    min_litres_used = request.args.get('min_litres_used', '')
    max_litres_used = request.args.get('max_litres_used', '')
    min_price = request.args.get('min_price', '')
    max_price = request.args.get('max_price', '')
    anomaly_threshold = request.args.get('anomaly_threshold', '')
    
    # Build query conditions
    conditions = []
    params = []
    
    # Convert HTML5 datetime-local to SQLite datetime format
    if start_date:
        # Replace 'T' with space for SQLite datetime format
        start_date = start_date.replace('T', ' ')
        conditions.append("datetime(date) >= datetime(?)")
        params.append(start_date)
    if end_date:
        end_date = end_date.replace('T', ' ')
        conditions.append("datetime(date) <= datetime(?)")
        params.append(end_date)
    if min_litres_used:
        conditions.append("litres_used_since_last >= ?")
        params.append(float(min_litres_used))
    if max_litres_used:
        conditions.append("litres_used_since_last <= ?")
        params.append(float(max_litres_used))
    if min_price:
        conditions.append("current_ppl >= ?")
        params.append(float(min_price))
    if max_price:
        conditions.append("current_ppl <= ?")
        params.append(float(max_price))
        
    # Simplified anomaly detection using moving average
    if anomaly_threshold and anomaly_threshold.strip():
        threshold = float(anomaly_threshold)
        # Get the average and standard deviation without using SQRT
        cursor.execute('''
            WITH stats AS (
                SELECT 
                    AVG(litres_used_since_last) as avg_usage,
                    AVG(litres_used_since_last * litres_used_since_last) - 
                    AVG(litres_used_since_last) * AVG(litres_used_since_last) as variance
                FROM readings
                WHERE litres_used_since_last IS NOT NULL
            )
            SELECT avg_usage, variance FROM stats
        ''')
        stats_row = cursor.fetchone()
        if stats_row and stats_row['avg_usage'] is not None:
            avg_usage = stats_row['avg_usage']
            # Approximate standard deviation using variance
            std_dev = (stats_row['variance'] ** 0.5) if stats_row['variance'] > 0 else 0
            
            upper_bound = avg_usage + (threshold * std_dev)
            lower_bound = avg_usage - (threshold * std_dev)
            
            conditions.append("(litres_used_since_last > ? OR litres_used_since_last < ?)")
            params.extend([upper_bound, lower_bound])
    
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    # Build the final query
    query = '''
        SELECT date, temperature, litres_remaining, litres_used_since_last,
               percentage_remaining, heating_degree_days, current_ppl, 
               cost_used, cost_to_fill, refill_detected
        FROM readings 
    '''
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY date DESC LIMIT ? OFFSET ?"
    
    # Get total count for pagination
    count_query = 'SELECT COUNT(*) as count FROM readings'
    if conditions:
        count_query += " WHERE " + " AND ".join(conditions)
    
    cursor.execute(count_query, params)
    total_records = cursor.fetchone()['count']
    total_pages = (total_records + per_page - 1) // per_page
    
    # Execute main query
    cursor.execute(query, params + [per_page, offset])
    records = cursor.fetchall()
    
    # Get statistics for the filtered data
    stats = None
    if records:
        cursor.execute('''
            SELECT 
                AVG(litres_used_since_last) as avg_usage,
                MIN(litres_used_since_last) as min_usage,
                MAX(litres_used_since_last) as max_usage,
                COUNT(*) as record_count,
                AVG(current_ppl) as avg_price,
                MIN(current_ppl) as min_price,
                MAX(current_ppl) as max_price,
                SUM(CASE WHEN cost_used != '' AND cost_used IS NOT NULL THEN CAST(cost_used as REAL) ELSE 0 END) as total_cost
            FROM readings
            ''' + (" WHERE " + " AND ".join(conditions) if conditions else ""),
            params
        )
        stats = cursor.fetchone()
    
    conn.close()
    
    # Convert the dates back to HTML datetime-local format for the form
    if start_date:
        start_date = start_date.replace(' ', 'T')
    if end_date:
        end_date = end_date.replace(' ', 'T')
    
    return render_template('records.html',
                         records=records,
                         page=page,
                         total_pages=total_pages,
                         start_date=start_date,
                         end_date=end_date,
                         min_litres_used=min_litres_used,
                         max_litres_used=max_litres_used,
                         min_price=min_price,
                         max_price=max_price,
                         anomaly_threshold=anomaly_threshold,
                         stats=stats)

@app.route('/records/edit/<date>', methods=['GET', 'POST'])
def edit_record(date):
    """Edit a specific record."""
    conn = get_db_connection()
    
    if request.method == 'POST':
        try:
            # Get the previous and next records for reference
            cursor = conn.cursor()
            cursor.execute('''
                SELECT litres_remaining 
                FROM readings 
                WHERE datetime(date) < datetime(?) 
                ORDER BY date DESC LIMIT 1
            ''', (date,))
            prev_record = cursor.fetchone()
            
            cursor.execute('''
                SELECT litres_remaining 
                FROM readings 
                WHERE datetime(date) > datetime(?) 
                ORDER BY date ASC LIMIT 1
            ''', (date,))
            next_record = cursor.fetchone()
            
            # Get the new values from the form
            new_litres = float(request.form.get('litres_remaining'))
            
            # Calculate percentage based on tank capacity (1225 litres)
            new_percentage = (new_litres / 1225.0) * 100
            
            # Calculate litres_used based on previous reading
            new_litres_used = 0
            if prev_record:
                prev_litres = float(prev_record['litres_remaining'])
                new_litres_used = max(0, prev_litres - new_litres)
            
            # Update the record
            cursor.execute('''
                UPDATE readings
                SET temperature = ?,
                    litres_remaining = ?,
                    litres_used_since_last = ?,
                    percentage_remaining = ?,
                    heating_degree_days = ?
                WHERE date = ?
            ''', (
                request.form.get('temperature'),
                new_litres,
                new_litres_used,
                new_percentage,
                request.form.get('heating_degree_days'),
                date
            ))
            
            # If this record has a next record, update its litres_used
            if next_record:
                next_litres = float(next_record['litres_remaining'])
                next_litres_used = max(0, new_litres - next_litres)
                cursor.execute('''
                    UPDATE readings
                    SET litres_used_since_last = ?
                    WHERE datetime(date) = (
                        SELECT datetime(date) 
                        FROM readings 
                        WHERE datetime(date) > datetime(?) 
                        ORDER BY date ASC LIMIT 1
                    )
                ''', (next_litres_used, date))
            
            conn.commit()
            flash('Record updated successfully', 'success')
            return redirect(url_for('records', 
                                  start_date=request.args.get('start_date'),
                                  end_date=request.args.get('end_date'),
                                  min_litres_used=request.args.get('min_litres_used'),
                                  max_litres_used=request.args.get('max_litres_used'),
                                  min_price=request.args.get('min_price'),
                                  max_price=request.args.get('max_price'),
                                  anomaly_threshold=request.args.get('anomaly_threshold'),
                                  page=request.args.get('page', 1)))
        except Exception as e:
            flash(f'Error updating record: {str(e)}', 'error')
    
    # Get the current record for editing
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    cursor.execute('''
        SELECT date, temperature, litres_remaining, litres_used_since_last,
               percentage_remaining, heating_degree_days
        FROM readings 
        WHERE date = ?
    ''', (date,))
    record = cursor.fetchone()
    
    conn.close()
    
    if not record:
        flash('Record not found', 'error')
        return redirect(url_for('records'))
    
    # Pass all current filter parameters to the template
    return render_template('edit_record.html', 
                         record=record,
                         start_date=request.args.get('start_date'),
                         end_date=request.args.get('end_date'),
                         min_litres_used=request.args.get('min_litres_used'),
                         max_litres_used=request.args.get('max_litres_used'),
                         min_price=request.args.get('min_price'),
                         max_price=request.args.get('max_price'),
                         anomaly_threshold=request.args.get('anomaly_threshold'),
                         page=request.args.get('page', 1))

@app.route('/records/delete/<date>', methods=['POST'])
def delete_record(date):
    """Delete a specific record."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM readings WHERE date = ?', (date,))
        conn.commit()
        flash('Record deleted successfully', 'success')
    except Exception as e:
        flash(f'Error deleting record: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('records'))

@app.route('/analysis_records')
def analysis_records():
    """Page for viewing and managing database analysis records."""
    conn = get_db_connection()
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    # Get total count
    cursor.execute('SELECT COUNT(*) as count FROM analysis_results')
    total_records = cursor.fetchone()['count']
    total_pages = (total_records + per_page - 1) // per_page
    
    # Get records for current page
    cursor.execute('''
        SELECT * FROM analysis_results 
        ORDER BY latest_reading_date DESC
        LIMIT ? OFFSET ?
    ''', (per_page, offset))
    records = cursor.fetchall()
    
    conn.close()
    
    return render_template('analysis_records.html',
                         records=records,
                         page=page,
                         total_pages=total_pages)

@app.route('/analysis_records/edit/<date>', methods=['GET', 'POST'])
def edit_analysis_record(date):
    """Edit a specific analysis record."""
    conn = get_db_connection()
    
    if request.method == 'POST':
        try:
            # Get all form fields
            form_data = {k: v for k, v in request.form.items() if k != 'csrf_token'}
            
            # Build the update query dynamically based on submitted fields
            set_clauses = []
            params = []
            for key, value in form_data.items():
                set_clauses.append(f"{key} = ?")
                params.append(value)
            
            # Add the WHERE clause parameter
            params.append(date)
            
            # Execute the update
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE analysis_results
                SET {", ".join(set_clauses)}
                WHERE latest_reading_date = ?
            ''', params)
            
            conn.commit()
            flash('Analysis record updated successfully', 'success')
            return redirect(url_for('analysis_records', page=request.args.get('page', 1)))
        except Exception as e:
            flash(f'Error updating analysis record: {str(e)}', 'error')
    
    # Get the current record for editing
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM analysis_results 
        WHERE latest_reading_date = ?
    ''', (date,))
    record = cursor.fetchone()
    
    # Get column info to determine field types
    cursor.execute("PRAGMA table_info(analysis_results)")
    columns = cursor.fetchall()
    column_types = {col['name']: col['type'] for col in columns}
    
    conn.close()
    
    if not record:
        flash('Analysis record not found', 'error')
        return redirect(url_for('analysis_records'))
    
    return render_template('edit_analysis_record.html', 
                         record=record,
                         column_types=column_types,
                         page=request.args.get('page', 1))

# Add routes for updating tank info and adding refills
@app.route('/update_tank_info', methods=['POST'])
def update_tank_info():
    flash('Tank information management is not supported in the current version', 'info')
    return redirect(url_for('analysis'))

@app.route('/add_refill', methods=['POST'])
def add_refill():
    flash('Refill management is not supported in the current version', 'info')
    return redirect(url_for('analysis'))

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True) 