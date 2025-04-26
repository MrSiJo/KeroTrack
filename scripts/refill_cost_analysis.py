import sqlite3
import os
from datetime import datetime, timedelta

def create_refill_costs_table(cursor):
    """Create a new table to store refill cost analysis if it doesn't exist"""
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS refill_cost_analysis (
        refill_id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_date TEXT,
        end_date TEXT,
        days_between INTEGER,
        litres_used REAL,
        actual_cost REAL,
        cost_per_day REAL,
        cost_per_month REAL,
        ppl_paid REAL,
        invoice_ref TEXT,
        order_ref TEXT,
        notes TEXT
    )
    ''')
    print("Created/verified refill_cost_analysis table")

def detect_refill_events(cursor):
    """Find refill events based on refill_detected flag in readings table"""
    print("Looking for refill events in the readings table...")
    
    # First, check if we have readings data
    cursor.execute("SELECT COUNT(*) FROM readings")
    count = cursor.fetchone()[0]
    print(f"Found {count} records in readings table")
    
    if count == 0:
        print("No reading records found - can't detect refill events")
        return []
    
    # Query for refill_detected = 'True' records
    cursor.execute('''
    SELECT r1.date as prev_date, r1.litres_remaining as prev_litres,
           r2.date as refill_date, r2.litres_remaining as refill_litres
    FROM readings r1
    JOIN readings r2 ON r2.rowid = r1.rowid + 1
    WHERE r2.refill_detected = 'True'
    ORDER BY r2.date
    ''')
    
    events = cursor.fetchall()
    print(f"Found {len(events)} refill events marked with refill_detected flag")
    
    # If no refill_detected events are found, fall back to the volume increase detection
    if not events:
        print("No refill_detected flags found, falling back to volume increase detection...")
        cursor.execute('''
        SELECT r1.date as prev_date, r1.litres_remaining as prev_litres,
               r2.date as refill_date, r2.litres_remaining as refill_litres
        FROM readings r1
        JOIN readings r2 ON r2.rowid = r1.rowid + 1
        WHERE (r2.litres_remaining - r1.litres_remaining) > 100  -- Significant increase threshold
        ORDER BY r2.date
        ''')
        
        events = cursor.fetchall()
        print(f"Found {len(events)} potential refill events based on volume increases")
    
    # Show sample events
    if events:
        print("\nSample detected refill events:")
        for event in events[:3]:
            prev_date, prev_litres, refill_date, refill_litres = event
            increase = refill_litres - prev_litres
            print(f"  {prev_date} ({prev_litres:.1f}L) → {refill_date} ({refill_litres:.1f}L) = +{increase:.1f}L")
    
    return events

def get_refill_orders(cursor):
    """Get all refill order records"""
    cursor.execute('''
    SELECT refill_date, actual_volume_litres, actual_ppl, total_cost, 
           invoice_ref, order_ref, notes
    FROM actual_refill_costs
    ORDER BY refill_date
    ''')
    
    orders = cursor.fetchall()
    print(f"Found {len(orders)} refill order records")
    
    # Show sample orders
    if orders:
        print("\nSample refill orders:")
        for order in orders[:3]:
            print(f"  Date: {order[0]}, Volume: {order[1]}L, Cost: £{order[3]}")
    
    return orders

def match_refills_with_orders(refill_events, refill_orders):
    """Match refill events with order records based on dates"""
    print("\nMatching refill events with order records...")
    matched_pairs = []
    
    # If we don't have detected refill events, use the order dates directly
    if not refill_events:
        print("No refill events detected, using order dates directly")
        
        for i in range(len(refill_orders)):
            order = refill_orders[i]
            order_date = order[0]
            
            # For each order, create a record
            order_data = {
                'order_date': order_date,
                'volume_delivered': order[1],
                'ppl': order[2],
                'total_cost': order[3],
                'invoice_ref': order[4],
                'order_ref': order[5],
                'notes': order[6]
            }
            
            matched_pairs.append(order_data)
            
        print(f"Created {len(matched_pairs)} order-based records")
        return matched_pairs
    
    # Otherwise match events to orders
    processed_orders = set()
    
    for event in refill_events:
        prev_date, prev_litres, refill_date, refill_litres = event
        
        # Parse refill date
        if ' ' in refill_date:
            refill_date_str = refill_date.split()[0]
        else:
            refill_date_str = refill_date
        
        try:
            refill_date_obj = datetime.strptime(refill_date_str, '%Y-%m-%d')
            best_match = None
            min_days_diff = float('inf')
            
            # Find closest order date (within 7 days)
            for i, order in enumerate(refill_orders):
                if i in processed_orders:
                    continue
                    
                order_date = order[0]
                if ' ' in order_date:
                    order_date_str = order_date.split()[0]
                else:
                    order_date_str = order_date
                
                order_date_obj = datetime.strptime(order_date_str, '%Y-%m-%d')
                days_diff = abs((refill_date_obj - order_date_obj).days)
                
                if days_diff <= 7 and days_diff < min_days_diff:
                    min_days_diff = days_diff
                    best_match = (i, order, days_diff)
            
            if best_match:
                idx, order, days_diff = best_match
                processed_orders.add(idx)
                
                matched_pairs.append({
                    'prev_date': prev_date,
                    'prev_litres': prev_litres,
                    'refill_date': refill_date,
                    'refill_litres': refill_litres,
                    'order_date': order[0],
                    'volume_delivered': order[1],
                    'ppl': order[2],
                    'total_cost': order[3],
                    'invoice_ref': order[4],
                    'order_ref': order[5],
                    'notes': order[6],
                    'days_diff': days_diff
                })
                print(f"  Matched event on {refill_date_str} with order on {order[0]} ({days_diff} days apart)")
            
        except Exception as e:
            print(f"  Error processing date {refill_date_str}: {e}")
    
    print(f"Found {len(matched_pairs)} matched refill events with orders")
    return matched_pairs

def calculate_metrics_between_orders(cursor, refill_orders):
    """Calculate cost metrics between consecutive order dates"""
    if len(refill_orders) <= 1:
        print("Need at least two order records to calculate metrics")
        return False
    
    # Clear existing data
    cursor.execute("DELETE FROM refill_cost_analysis")
    print("\nCalculating cost metrics between consecutive orders...")
    
    # Convert orders to list of dictionaries
    orders = []
    for order in refill_orders:
        orders.append({
            'order_date': order[0],
            'volume_delivered': order[1],
            'ppl': order[2],
            'total_cost': order[3],
            'invoice_ref': order[4],
            'order_ref': order[5],
            'notes': order[6]
        })
    
    # Process consecutive orders
    for i in range(1, len(orders)):
        current = orders[i]
        previous = orders[i-1]
        
        try:
            # Get dates
            start_date_str = previous['order_date'].split()[0] if ' ' in previous['order_date'] else previous['order_date']
            end_date_str = current['order_date'].split()[0] if ' ' in current['order_date'] else current['order_date']
            
            print(f"  Analyzing period from {start_date_str} to {end_date_str}")
            
            # Calculate days between orders
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            days_between = (end_date - start_date).days
            
            if days_between <= 0:
                print(f"  Skipping period with invalid days ({days_between}) between {start_date_str} and {end_date_str}")
                continue
            
            # Estimate usage (assume previous delivery was used)
            litres_used = previous['volume_delivered']
            
            # Cost metrics
            actual_cost = current['total_cost']
            cost_per_day = actual_cost / days_between
            cost_per_month = cost_per_day * 30.44  # Average days in month
            
            print(f"  Period {start_date_str} to {end_date_str} ({days_between} days):")
            print(f"    Used: {litres_used:.1f}L, Cost: £{actual_cost:.2f}")
            print(f"    Cost per day: £{cost_per_day:.2f}, Cost per month: £{cost_per_month:.2f}")
            
            # Store in database
            cursor.execute('''
            INSERT INTO refill_cost_analysis (
                start_date, end_date, days_between, litres_used, actual_cost,
                cost_per_day, cost_per_month, ppl_paid, invoice_ref, order_ref, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                start_date_str, end_date_str, days_between, litres_used, actual_cost,
                cost_per_day, cost_per_month, current['ppl'], current['invoice_ref'],
                current['order_ref'], current['notes']
            ))
            
        except Exception as e:
            print(f"  Error processing period: {e}")
    
    return True

def calculate_cost_metrics(cursor, matched_pairs):
    """Calculate cost metrics between refills based on matched refill events and orders"""
    if len(matched_pairs) <= 1:
        print("Need at least two refill events to calculate metrics between them")
        return False
    
    # Clear existing data
    cursor.execute("DELETE FROM refill_cost_analysis")
    print("\nCalculating cost metrics between refill events...")
    
    # Sort by refill/order date
    if 'refill_date' in matched_pairs[0]:
        matched_pairs.sort(key=lambda x: datetime.strptime(x['refill_date'].split()[0] 
                                                         if ' ' in x['refill_date'] 
                                                         else x['refill_date'], '%Y-%m-%d'))
    else:
        matched_pairs.sort(key=lambda x: datetime.strptime(x['order_date'].split()[0] 
                                                         if ' ' in x['order_date'] 
                                                         else x['order_date'], '%Y-%m-%d'))
    
    print(f"Processing {len(matched_pairs)} ordered refill records")
    
    # Process consecutive refill events
    for i in range(1, len(matched_pairs)):
        current = matched_pairs[i]
        previous = matched_pairs[i-1]
        
        try:
            # Determine start and end dates
            if 'refill_date' in current:
                # Using detected refill events
                start_date_str = previous['refill_date'].split()[0] if ' ' in previous['refill_date'] else previous['refill_date']
                end_date_str = current['refill_date'].split()[0] if ' ' in current['refill_date'] else current['refill_date']
                litres_used = previous['refill_litres'] - current['prev_litres']
            else:
                # Using order dates directly
                start_date_str = previous['order_date'].split()[0] if ' ' in previous['order_date'] else previous['order_date']
                end_date_str = current['order_date'].split()[0] if ' ' in current['order_date'] else current['order_date']
                # Estimate usage (assume all delivered oil was used)
                litres_used = previous['volume_delivered']
            
            print(f"  Analyzing period from {start_date_str} to {end_date_str}")
            
            # Calculate days between refills
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            days_between = (end_date - start_date).days
            
            if days_between <= 0:
                print(f"  Skipping period with invalid days ({days_between}) between {start_date_str} and {end_date_str}")
                continue
            
            # Cost metrics
            actual_cost = current['total_cost']
            cost_per_day = actual_cost / days_between
            cost_per_month = cost_per_day * 30.44  # Average days in month
            
            print(f"  Period {start_date_str} to {end_date_str} ({days_between} days):")
            print(f"    Used: {litres_used:.1f}L, Cost: £{actual_cost:.2f}")
            print(f"    Cost per day: £{cost_per_day:.2f}, Cost per month: £{cost_per_month:.2f}")
            
            # Store in database
            cursor.execute('''
            INSERT INTO refill_cost_analysis (
                start_date, end_date, days_between, litres_used, actual_cost,
                cost_per_day, cost_per_month, ppl_paid, invoice_ref, order_ref, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                start_date_str, end_date_str, days_between, litres_used, actual_cost,
                cost_per_day, cost_per_month, current['ppl'], current['invoice_ref'],
                current['order_ref'], current['notes']
            ))
            
        except Exception as e:
            print(f"  Error processing period: {e}")
    
    return True

def main():
    print("Analyzing refill costs and calculating metrics...")
    
    # Connect to the database
    db_path = os.path.join('..', 'data', 'oil_data.db')
    print(f"Using database at: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create table if it doesn't exist
        create_refill_costs_table(cursor)
        
        # Try to detect refill events from readings
        refill_events = detect_refill_events(cursor)
        
        # Get all refill orders
        refill_orders = get_refill_orders(cursor)
        
        analysis_done = False
        
        # If we have enough refill events that match with orders, use that approach
        if refill_events:
            matched_pairs = match_refills_with_orders(refill_events, refill_orders)
            if len(matched_pairs) > 1:
                analysis_done = calculate_cost_metrics(cursor, matched_pairs)
        
        # If refill event detection didn't work, use consecutive orders approach
        if not analysis_done:
            print("\nSwitching to consecutive orders analysis method")
            calculate_metrics_between_orders(cursor, refill_orders)
        
        # Display results
        print("\nSaved refill cost analysis results:")
        cursor.execute("SELECT * FROM refill_cost_analysis ORDER BY start_date")
        results = cursor.fetchall()
        
        if results:
            for result in results:
                print(f"  Period {result[1]} to {result[2]} ({result[3]} days):")
                print(f"    Used: {result[4]:.1f}L, Cost: £{result[5]:.2f}")
                print(f"    Cost per day: £{result[6]:.2f}, Cost per month: £{result[7]:.2f}")
        else:
            print("No results were saved in the database")
        
        conn.commit()
        print("\nAnalysis complete")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    main() 