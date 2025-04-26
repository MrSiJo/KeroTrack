#!/usr/bin/env python3

"""
Generate statistics from the oil monitoring database
"""

import os
import sys
import sqlite3
from datetime import datetime
import pandas as pd
import numpy as np
from utils.config_loader import load_config, get_config_value

# Add parent directory to path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

# Connect to the database
config = load_config()
db_path = get_config_value(config, 'database', 'path', default=os.path.join(parent_dir, 'data', 'KeroTrack_data.db'))
print(f"Database path: {db_path}")

def get_table_info():
    """Get information about the tables in the database"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get a list of all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        print("\n=== Database Tables ===")
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"{table}: {count} rows")
        
        conn.close()
        return tables
    except Exception as e:
        print(f"Error getting table info: {e}")
        return []

def analyze_readings():
    """Analyze the readings table"""
    try:
        conn = sqlite3.connect(db_path)
        
        # Load data into pandas
        df = pd.read_sql_query("SELECT * FROM readings", conn)
        
        if df.empty:
            print("No readings found in database")
            conn.close()
            return
        
        # Convert date to datetime
        df['date'] = pd.to_datetime(df['date'])
        
        # Get date range
        min_date = df['date'].min()
        max_date = df['date'].max()
        date_range = (max_date - min_date).days
        
        # Count refills and leaks
        refill_count = df[df['refill_detected'] == 'y'].shape[0]
        leak_count = df[df['leak_detected'] == 'y'].shape[0]
        
        # Temperature stats
        temp_min = df['temperature'].min()
        temp_max = df['temperature'].max()
        temp_avg = df['temperature'].mean()
        
        # Oil level stats
        level_min = df['litres_remaining'].min()
        level_max = df['litres_remaining'].max()
        level_avg = df['litres_remaining'].mean()
        
        # HDD stats if available
        if 'heating_degree_days' in df.columns:
            hdd_sum = df['heating_degree_days'].sum()
            hdd_avg = df['heating_degree_days'].mean()
        else:
            hdd_sum = hdd_avg = "N/A"
        
        # Print statistics
        print("\n=== Readings Analysis ===")
        print(f"Date range: {min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')} ({date_range} days)")
        print(f"Number of readings: {df.shape[0]} ({df.shape[0]/date_range:.1f} per day)")
        print(f"Detected refills: {refill_count}")
        print(f"Detected leaks: {leak_count}")
        print(f"Temperature range: {temp_min:.1f}°C to {temp_max:.1f}°C (avg: {temp_avg:.1f}°C)")
        print(f"Oil level range: {level_min:.1f}L to {level_max:.1f}L (avg: {level_avg:.1f}L)")
        print(f"Total heating degree days: {hdd_sum}")
        print(f"Average heating degree days: {hdd_avg}")
        
        # Calculate consumption rate
        if refill_count > 0:
            # Group by month
            df['month'] = df['date'].dt.to_period('M')
            monthly = df.groupby('month').agg({
                'litres_used_since_last': 'sum',
                'heating_degree_days': 'sum'
            }).reset_index()
            
            # Print monthly consumption
            print("\n=== Monthly Consumption ===")
            for _, row in monthly.iterrows():
                month_str = str(row['month'])
                used = row['litres_used_since_last']
                hdd = row['heating_degree_days']
                if pd.notna(used) and used > 0:
                    print(f"{month_str}: {used:.1f}L used, {hdd:.1f} HDD, {used/hdd:.2f}L per HDD" if pd.notna(hdd) and hdd > 0 else f"{month_str}: {used:.1f}L used")
        
        conn.close()
    except Exception as e:
        print(f"Error analyzing readings: {e}")

def analyze_refill_costs():
    """Analyze the actual refill costs"""
    try:
        conn = sqlite3.connect(db_path)
        
        # Check if table exists
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='actual_refill_costs'")
        if not cursor.fetchone():
            print("\n=== Refill Costs ===")
            print("Table does not exist")
            conn.close()
            return
        
        # Load data into pandas
        df = pd.read_sql_query("SELECT * FROM actual_refill_costs", conn)
        
        if df.empty:
            print("\n=== Refill Costs ===")
            print("No refill cost data found")
            conn.close()
            return
        
        # Convert date to datetime
        df['refill_date'] = pd.to_datetime(df['refill_date'])
        
        # Sort by date
        df = df.sort_values('refill_date')
        
        # Calculate stats
        total_volume = df['actual_volume_litres'].sum()
        total_cost = df['total_cost'].sum()
        avg_ppl = df['actual_ppl'].mean()
        min_ppl = df['actual_ppl'].min()
        max_ppl = df['actual_ppl'].max()
        
        # Print statistics
        print("\n=== Refill Costs Analysis ===")
        print(f"Total refills: {df.shape[0]}")
        print(f"Date range: {df['refill_date'].min().strftime('%Y-%m-%d')} to {df['refill_date'].max().strftime('%Y-%m-%d')}")
        print(f"Total volume purchased: {total_volume:.1f}L")
        print(f"Total cost: £{total_cost:.2f}")
        print(f"Average price per liter: {avg_ppl:.2f}p")
        print(f"Price range: {min_ppl:.2f}p to {max_ppl:.2f}p")
        
        # Calculate annual costs
        df['year'] = df['refill_date'].dt.year
        yearly = df.groupby('year').agg({
            'actual_volume_litres': 'sum',
            'total_cost': 'sum'
        }).reset_index()
        
        # Print yearly totals
        print("\n=== Annual Costs ===")
        for _, row in yearly.iterrows():
            year = row['year']
            volume = row['actual_volume_litres']
            cost = row['total_cost']
            print(f"{year}: {volume:.1f}L, £{cost:.2f} (avg: {cost/volume*100:.2f}p per liter)")
        
        conn.close()
    except Exception as e:
        print(f"Error analyzing refill costs: {e}")

def analyze_analysis_results():
    """Analyze the analysis results"""
    try:
        conn = sqlite3.connect(db_path)
        
        # Check if table exists
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='analysis_results'")
        if not cursor.fetchone():
            print("\n=== Analysis Results ===")
            print("Table does not exist")
            conn.close()
            return
        
        # Load data into pandas
        df = pd.read_sql_query("SELECT * FROM analysis_results", conn)
        
        if df.empty:
            print("\n=== Analysis Results ===")
            print("No analysis results found")
            conn.close()
            return
        
        # Convert date columns to datetime
        if 'latest_reading_date' in df.columns:
            df['latest_reading_date'] = pd.to_datetime(df['latest_reading_date'])
        if 'latest_analysis_date' in df.columns:
            df['latest_analysis_date'] = pd.to_datetime(df['latest_analysis_date'])
        
        # Get the most recent analysis
        latest = df.sort_values('latest_analysis_date', ascending=False).iloc[0]
        
        # Print statistics
        print("\n=== Latest Analysis Results ===")
        print(f"Analysis date: {latest['latest_analysis_date']}")
        
        # Only print the useful metrics
        metrics = [
            'days_since_refill', 
            'total_consumption_since_refill',
            'avg_daily_consumption_l',
            'estimated_days_remaining',
            'estimated_empty_date',
            'consumption_per_hdd_l',
            'upcoming_month_hdd',
            'estimated_daily_consumption_hdd_l'
        ]
        
        for metric in metrics:
            if metric in latest and pd.notna(latest[metric]):
                value = latest[metric]
                # Format differently based on the type
                if isinstance(value, float):
                    print(f"{metric}: {value:.2f}")
                else:
                    print(f"{metric}: {value}")
        
        conn.close()
    except Exception as e:
        print(f"Error analyzing analysis results: {e}")

if __name__ == "__main__":
    tables = get_table_info()
    
    if "readings" in tables:
        analyze_readings()
    
    if "actual_refill_costs" in tables:
        analyze_refill_costs()
    
    if "analysis_results" in tables:
        analyze_analysis_results()
    
    print("\nAnalysis complete.") 