import sqlite3
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config_loader import load_config, get_config_value

config = load_config()
db_path = get_config_value(config, 'database', 'path', default='data/KeroTrack_data.db')

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Get a sample of records with cost information
cursor.execute('''
    SELECT 
        date,
        litres_remaining,
        litres_used_since_last,
        current_ppl,
        cost_used,
        cost_to_fill,
        refill_detected,
        litres_to_order
    FROM readings 
    WHERE current_ppl IS NOT NULL 
       OR cost_used IS NOT NULL 
       OR cost_to_fill IS NOT NULL 
       OR refill_detected = 'True'
    ORDER BY date DESC 
    LIMIT 5
''')

rows = cursor.fetchall()
print("\nSample records with cost information:")
print("-" * 80)
for row in rows:
    print(f"\nDate: {row['date']}")
    print(f"Litres Remaining: {row['litres_remaining']:.1f}")
    print(f"Litres Used: {row['litres_used_since_last']:.1f}")
    print(f"Price per Litre: {row['current_ppl'] if row['current_ppl'] is not None else 'N/A'}")
    print(f"Cost Used: {row['cost_used']}")
    print(f"Cost to Fill: {row['cost_to_fill']}")
    print(f"Refill Detected: {row['refill_detected']}")
    print(f"Litres to Order: {row['litres_to_order'] if row['litres_to_order'] is not None else 'N/A'}")

# Get some statistics about cost data
cursor.execute('''
    SELECT 
        COUNT(*) as total_records,
        COUNT(current_ppl) as records_with_price,
        MIN(current_ppl) as min_price,
        MAX(current_ppl) as max_price,
        AVG(current_ppl) as avg_price
    FROM readings
    WHERE current_ppl IS NOT NULL
''')

stats = cursor.fetchone()
print("\nPrice Statistics:")
print("-" * 80)
print(f"Total Records: {stats['total_records']}")
print(f"Records with Price: {stats['records_with_price']}")
if stats['min_price'] is not None:
    print(f"Min Price per Litre: {stats['min_price']:.2f}")
    print(f"Max Price per Litre: {stats['max_price']:.2f}")
    print(f"Avg Price per Litre: {stats['avg_price']:.2f}")

conn.close() 