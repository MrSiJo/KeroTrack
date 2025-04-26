#!/usr/bin/env python3

"""
Database inspection script that examines the oil database structure and 
provides sample data from each table.
"""

import sqlite3
import os
import sys
from datetime import datetime

# Add parent directory to path so we can import from parent
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from db_connection import get_db_connection
from utils.config_loader import load_config, get_config_value

def inspect_table(conn, table_name):
    """Display schema and sample data from a table."""
    try:
        cursor = conn.cursor()
        
        # Get schema
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        
        if not columns:
            print(f"\nTable '{table_name}' does not exist.")
            return False
            
        print(f"\n===== Table: {table_name} =====")
        print("\nSchema:")
        for col in columns:
            col_id, name, data_type, notnull, default_val, pk = col
            pk_str = "PRIMARY KEY" if pk else ""
            null_str = "NOT NULL" if notnull else ""
            default_str = f"DEFAULT {default_val}" if default_val else ""
            print(f"  {name} ({data_type}) {pk_str} {null_str} {default_str}".strip())
        
        # Get row count
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        print(f"\nRow count: {count}")
        
        if count == 0:
            print("  No data in table")
            return True
            
        # Get sample data (first 5 rows)
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
        rows = cursor.fetchall()
        
        # Get column names for pretty printing
        column_names = [col[1] for col in columns]
        
        print("\nSample data (up to 5 rows):")
        # Print header
        header = " | ".join(column_names)
        print(f"  {header}")
        print(f"  {'-' * len(header)}")
        
        # Print rows
        for row in rows:
            formatted_row = []
            for i, value in enumerate(row):
                # Format date fields for readability if they look like timestamps
                if isinstance(value, str) and column_names[i].lower().endswith('date'):
                    try:
                        dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
                        value = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        pass
                # Truncate long strings
                if isinstance(value, str) and len(value) > 50:
                    value = value[:47] + "..."
                formatted_row.append(str(value))
            print(f"  {' | '.join(formatted_row)}")
        
        # For certain tables, show statistical summaries
        if table_name in ['readings', 'actual_refill_costs', 'analysis_results']:
            print("\nStatistical summary:")
            
            # Get numeric columns
            numeric_cols = [col[1] for col in columns 
                           if col[2].upper() in ['REAL', 'INTEGER', 'NUMERIC', 'FLOAT', 'DOUBLE']]
            
            for col in numeric_cols:
                cursor.execute(f"SELECT MIN({col}), MAX({col}), AVG({col}) FROM {table_name} WHERE {col} IS NOT NULL")
                min_val, max_val, avg_val = cursor.fetchone()
                if min_val is not None:
                    print(f"  {col}: Min={min_val}, Max={max_val}, Avg={avg_val:.2f if avg_val else 'N/A'}")
        
        return True
    
    except Exception as e:
        print(f"Error inspecting table {table_name}: {e}")
        return False

def main():
    """Main function to inspect database tables."""
    # Connect to the database
    config = load_config()
    db_path = get_config_value(config, 'database', 'path', default=os.path.join(parent_dir, 'data', 'KeroTrack_data.db'))
    print(f"Inspecting database at: {db_path}")
    
    with get_db_connection(db_path) as conn:
        # Get all table names
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        print(f"Found {len(tables)} tables: {', '.join(tables)}")
        
        # Inspect each table
        for table in tables:
            inspect_table(conn, table)
            
        # Also check for expected tables that might be missing
        expected_tables = ['readings', 'actual_refill_costs', 'analysis_results', 'cost_analysis', 'hdd_data']
        missing_tables = [t for t in expected_tables if t not in tables]
        
        if missing_tables:
            print(f"\nMissing expected tables: {', '.join(missing_tables)}")
            
            # Check if actual_refill_costs exists in the schema even if empty
            if 'actual_refill_costs' in missing_tables:
                # Create the table to inspect it
                cursor.execute('''
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
                conn.commit()
                
                # Inspect the newly created table
                print("\nInspecting newly created 'actual_refill_costs' table:")
                inspect_table(conn, 'actual_refill_costs')

if __name__ == "__main__":
    main() 