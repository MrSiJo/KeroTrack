#!/usr/bin/env python3

"""
Bulk import script for historical oil delivery data.
This script takes a text file containing historical delivery records and imports them into the cost analysis database.
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# Add parent directory to path so we can import from parent
parent_dir = str(Path(__file__).resolve().parent.parent)
sys.path.append(parent_dir)

from db_connection import get_db_connection

def parse_money(money_str):
    """Convert money string to float, handling any currency symbols."""
    return float(str(money_str).replace('£', '').replace(',', ''))

def parse_date(date_str):
    """Parse date in DD/MM/YYYY format to database format."""
    try:
        return datetime.strptime(date_str, '%d/%m/%Y').strftime('%Y-%m-%d 00:00:00')
    except ValueError as e:
        print(f"Error parsing date {date_str}: {e}")
        return None

def parse_delivery_record(line):
    """Parse a single delivery record line."""
    # Skip empty lines or header lines
    if not line.strip() or 'Product' in line:
        return None
        
    try:
        # Split the line by hyphen and clean up each part
        parts = [p.strip() for p in line.split('-')]
        
        # New format: Product - Quantity - Service - Delivery By - ppl - Order Total
        if len(parts) != 6:
            print(f"Warning: Expected 6 fields, got {len(parts)} in line: {line}")
            return None
            
        product, quantity, service, delivery_date, ppl, total = parts
        
        # Parse numeric values
        quantity = float(quantity)
        ppl = float(ppl)
        total_cost = float(total)
        
        return {
            'delivery_date': parse_date(delivery_date),
            'quantity': quantity,
            'ppl': ppl,
            'total_cost': total_cost,
            'notes': f"Historical import - {product.strip()}"
        }
        
    except Exception as e:
        print(f"Error parsing line: {line}")
        print(f"Error details: {e}")
        return None

def import_historical_data(data_str, db_path):
    """Import historical delivery data from a string."""
    records = []
    
    # Parse each line
    for line in data_str.split('\n'):
        record = parse_delivery_record(line)
        if record:
            records.append(record)
    
    # Sort records by date
    records.sort(key=lambda x: x['delivery_date'] if x['delivery_date'] else '')
    
    # Connect to database and import records
    with get_db_connection(db_path) as conn:
        c = conn.cursor()
        
        # Ensure the table exists
        c.execute('''
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
        
        # Import each record
        for record in records:
            if not record['delivery_date']:
                continue
                
            try:
                c.execute('''
                INSERT OR REPLACE INTO actual_refill_costs
                (refill_date, actual_volume_litres, actual_ppl, total_cost, notes, entry_date)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    record['delivery_date'],
                    record['quantity'],
                    record['ppl'],
                    record['total_cost'],
                    record['notes'],
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                ))
                
                print(f"Imported: {record['delivery_date']} - {record['quantity']}L at {record['ppl']}ppl (Total: {record['total_cost']:.2f})")
                
            except Exception as e:
                print(f"Error importing record: {record}")
                print(f"Error details: {e}")
                continue
        
        conn.commit()
    
    return len(records)

def main():
    """Main function to handle command line usage."""
    if len(sys.argv) != 2:
        print("Usage: python import_historical_costs.py <data_file>")
        print("The data file should contain delivery records in the format:")
        print("Product - Quantity - Service - Delivery By - ppl - Order Total")
        sys.exit(1)
        
    data_file = sys.argv[1]
    if not os.path.exists(data_file):
        print(f"Error: File not found: {data_file}")
        sys.exit(1)
        
    try:
        with open(data_file, 'r') as f:
            data = f.read()
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
        
    # Get database path from parent directory
    db_path = os.path.join(parent_dir, 'data', 'oil_data.db')
    
    # Import the data
    num_imported = import_historical_data(data, db_path)
    print(f"\nSuccessfully imported {num_imported} records")
    
    # Suggest next steps
    print("\nNext steps:")
    print("1. Review the imported data:")
    print("   python oil_cost_analysis.py --list-refills")
    print("2. Run the cost analysis:")
    print("   python oil_cost_analysis.py --analyze")

if __name__ == '__main__':
    main() 