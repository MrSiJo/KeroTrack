import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os
import sys
import re

# Add parent directory to path so we can import from parent
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from db_connection import get_db_connection
from utils.config_loader import load_config, get_config_value

# Load configuration
config = load_config(os.path.join(parent_dir, 'config'))

# Database configuration
DB_PATH = os.path.join(parent_dir, get_config_value(config, 'database', 'path'))

def fetch_hdd_data():
    url = "https://vesma.com/ddd2/36month.htm"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    pre_content = soup.find('pre').text.strip()
    
    lines = pre_content.split('\n')[2:]  # Skip the first two lines
    data = []
    current_year = datetime.now().year
    
    for line in lines[-36:]:  # Get last 36 months
        parts = line.split(':')
        if len(parts) != 2:
            continue
        
        date_part, values = parts
        month, year = map(int, date_part.strip().split('/'))
        full_year = 2000 + year  # Assuming years are in the format '23' for 2023
        date = datetime(full_year, month, 1).strftime("%Y-%m-%d")
        
        hdd = float(values.split()[2])  # HDD for region 3 (index 2)
        data.append((date, hdd))
    
    # Sort data chronologically
    return sorted(data, key=lambda x: x[0])

def clear_table(conn):
    cursor = conn.cursor()
    cursor.execute('DELETE FROM hdd_data')
    conn.commit()

def update_database(conn, data):
    cursor = conn.cursor()
    
    for date, hdd in data:
        cursor.execute('''
            INSERT INTO hdd_data (date, hdd)
            VALUES (?, ?)
        ''', (date, hdd))
    
    conn.commit()

if __name__ == "__main__":
    hdd_data = fetch_hdd_data()
    
    with get_db_connection(DB_PATH) as conn:
        clear_table(conn)
        update_database(conn, hdd_data)
    
    print(f"Cleared existing data and inserted {len(hdd_data)} months of fresh HDD data in chronological order.")