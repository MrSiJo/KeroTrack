import sqlite3
import json
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.config_loader import load_config, get_config_value

def main():
    # Get parent directory
    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    config = load_config(os.path.join(parent_dir, 'config'))
    db_path = get_config_value(config, 'database', 'path', default=os.path.join(parent_dir, 'data', 'KeroTrack_data.db'))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all table names
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    
    print("Tables in the database:")
    for table in tables:
        table_name = table['name']
        print(f"- {table_name}")
        
        # Get table schema
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        print("  Columns:")
        for col in columns:
            print(f"  - {col['name']} ({col['type']})")
    
    # Check if needed tables exist
    needed_tables = ['refills', 'tank_info']
    for table_name in needed_tables:
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        exists = cursor.fetchone()
        if not exists:
            print(f"\nTable '{table_name}' is missing and will be created by web_app.py when needed.")
    
    # Close the connection
    conn.close()

if __name__ == "__main__":
    main() 