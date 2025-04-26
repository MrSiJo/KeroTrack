import sqlite3
import sys
import os

def query_db(db_path, start_time, end_time):
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT strftime('%Y-%m-%d %H:%M:%S', date) as formatted_date, 
                   litres_remaining, 
                   air_gap_cm, 
                   refill_detected, 
                   leak_detected 
            FROM readings 
            WHERE date BETWEEN ? AND ? 
            ORDER BY date;
            """, (start_time, end_time))
        
        rows = cursor.fetchall()
        
        if rows:
            print("date                 | litres | air_gap | refill | leak")
            print("---------------------+--------+---------+--------+------")
            for row in rows:
                print(f"{row[0]:<21}| {row[1]:<6.1f} | {row[2]:<7.1f} | {row[3]:<6} | {row[4]:<4}")
        else:
            print(f"No readings found between {start_time} and {end_time}")
            
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # Get parent directory
    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
    # Database path
    db = os.path.join(parent_dir, 'data', 'oil_data.db')
    
    # Use the provided exact timestamps
    start = '2025-03-16 07:26:10' # More specific start based on user mention
    end = '2025-03-16 07:56:07'   # More specific end based on user mention
    
    # Widen slightly to catch adjacent records for context
    start_query = '2025-03-16 07:20:00' 
    end_query = '2025-03-16 08:00:00'
    
    print(f"Querying between {start_query} and {end_query}...")
    print(f"Using database: {db}")
    query_db(db, start_query, end_query) 