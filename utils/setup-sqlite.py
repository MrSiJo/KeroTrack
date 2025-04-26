import sqlite3
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config_loader import load_config, get_config_value

def setup_database(db_path=None):
    """Set up the database or add missing columns if it already exists."""
    if db_path is None:
        config = load_config()
        db_path = get_config_value(config, 'database', 'path', default='data/KeroTrack_data.db')
    new_db = not os.path.exists(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    if new_db:
        print(f"Creating new database: {db_path}")
    else:
        print(f"Updating existing database: {db_path}")

    c.execute('PRAGMA journal_mode=WAL;')
    
    # Define tables and their columns
    tables = {
        'readings': [
            ('date', 'TEXT'),
            ('id', 'TEXT'),
            ('temperature', 'REAL'),
            ('litres_remaining', 'REAL'),
            ('litres_used_since_last', 'REAL'),
            ('percentage_remaining', 'REAL'),
            ('oil_depth_cm', 'REAL'),
            ('air_gap_cm', 'REAL'),
            ('current_ppl', 'REAL'),
            ('cost_used', 'TEXT'),
            ('cost_to_fill', 'TEXT'),
            ('heating_degree_days', 'REAL'),
            ('seasonal_efficiency', 'REAL'),
            ('refill_detected', 'TEXT'),
            ('leak_detected', 'TEXT'),
            ('raw_flags', 'TEXT'),
            ('litres_to_order', 'REAL'),
            ('bars_remaining', 'INTEGER')
        ],
        'analysis_results': [
            ('latest_reading_date', 'TEXT PRIMARY KEY'),
            ('latest_analysis_date', 'TEXT'),
            ('latest_reading_refill_detected', 'TEXT'),
            ('latest_reading_leak_detected', 'TEXT'),
            ('days_since_refill', 'INTEGER'),
            ('total_consumption_since_refill', 'REAL'),
            ('avg_daily_consumption_l', 'REAL'),
            ('estimated_days_remaining', 'REAL'),
            ('estimated_empty_date', 'TEXT'),
            ('consumption_per_hdd_l', 'REAL'),
            ('upcoming_month_hdd', 'REAL'),
            ('estimated_daily_consumption_hdd_l', 'REAL'),
            ('estimated_daily_hot_water_consumption_l', 'REAL'),
            ('estimated_daily_heating_consumption_l', 'REAL'),
            ('seasonal_heating_factor', 'REAL'),
            ('remaining_days_empty_hdd', 'REAL'),
            ('remaining_date_empty_hdd', 'TEXT')
        ],
        'hdd_data': [
            ('date', 'TEXT PRIMARY KEY'),
            ('hdd', 'REAL')
        ],
        'actual_refill_costs': [
            ('refill_date', 'TEXT PRIMARY KEY'),
            ('actual_volume_litres', 'REAL'),
            ('actual_ppl', 'REAL'),
            ('total_cost', 'REAL'),
            ('invoice_ref', 'TEXT'),
            ('notes', 'TEXT'),
            ('entry_date', 'TEXT'),
            ('order_date', 'TEXT'),
            ('order_ref', 'TEXT')
        ],
        'cost_analysis': [
            ('analysis_date', 'TEXT PRIMARY KEY'),
            ('latest_period_start', 'TEXT'),
            ('latest_period_end', 'TEXT'),
            ('latest_period_days', 'INTEGER'),
            ('latest_refill_amount', 'REAL'),
            ('latest_refill_cost', 'REAL'),
            ('latest_refill_ppl', 'REAL'),
            ('latest_total_consumption', 'REAL'),
            ('latest_total_cost', 'REAL'),
            ('latest_daily_cost', 'REAL'),
            ('latest_weekly_cost', 'REAL'),
            ('latest_monthly_cost', 'REAL'),
            ('days_since_refill', 'INTEGER'),
            ('avg_period_cost', 'REAL'),
            ('avg_period_consumption', 'REAL'),
            ('avg_daily_cost', 'REAL'),
            ('avg_weekly_cost', 'REAL'),
            ('avg_monthly_cost', 'REAL'),
            ('avg_annual_cost', 'REAL'),
            ('avg_cost_per_hdd', 'REAL'),
            ('avg_consumption_per_hdd', 'REAL'),
            ('avg_cost_per_kwh', 'REAL'),
            ('avg_daily_energy_kwh', 'REAL'),
            ('avg_cost_per_heat_unit', 'REAL'),
            ('total_refill_periods', 'INTEGER'),
            ('percentage_with_actual_data', 'REAL'),
            ('energy_efficiency', 'REAL'),
            ('analysis_data', 'TEXT')
        ],
        'energy_metrics': [
            ('period_start', 'TEXT'),
            ('period_end', 'TEXT'),
            ('total_energy_kwh', 'REAL'),
            ('delivered_energy_kwh', 'REAL'),
            ('cost_per_kwh', 'REAL'),
            ('cost_per_useful_kwh', 'REAL'),
            ('daily_energy_kwh', 'REAL'),
            ('energy_efficiency', 'REAL'),
            ('analysis_date', 'TEXT'),
            ('PRIMARY KEY', '(period_start, period_end)')
        ],
        'refill_periods': [
            ('start_date', 'TEXT'),
            ('end_date', 'TEXT'),
            ('days', 'INTEGER'),
            ('total_consumption', 'REAL'),
            ('average_ppl', 'REAL'),
            ('total_cost', 'REAL'),
            ('daily_cost', 'REAL'),
            ('weekly_cost', 'REAL'),
            ('monthly_cost', 'REAL'),
            ('refill_amount_liters', 'REAL'),
            ('refill_ppl', 'REAL'),
            ('refill_cost', 'REAL'),
            ('refill_invoice', 'TEXT'),
            ('refill_notes', 'TEXT'),
            ('used_actual_cost', 'INTEGER'),
            ('analysis_date', 'TEXT'),
            ('total_hdd', 'REAL'),
            ('cost_per_hdd', 'REAL'),
            ('consumption_per_hdd', 'REAL'),
            ('PRIMARY KEY', '(start_date, end_date)')
        ]
    }

    for table_name, columns in tables.items():
        # Check if table exists
        c.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        table_exists = c.fetchone() is not None

        if not table_exists:
            # Create table if it doesn't exist
            # Handle composite primary keys and other constraints appropriately
            columns_sql = []
            for col in columns:
                if col[0] == 'PRIMARY KEY':
                    columns_sql.append(col[1])
                else:
                    columns_sql.append(f"{col[0]} {col[1]}")
            
            columns_sql_str = ', '.join(columns_sql)
            c.execute(f"CREATE TABLE {table_name} ({columns_sql_str})")
            print(f"Created table: {table_name}")
        else:
            # Check for missing columns and add them
            c.execute(f"PRAGMA table_info({table_name})")
            existing_columns = {row[1]: row[2] for row in c.fetchall()}
            for col_name, col_type in columns:
                # Skip PRIMARY KEY constraint when adding columns
                if col_name != 'PRIMARY KEY' and col_name not in existing_columns:
                    c.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
                    print(f"Added missing column to {table_name}: {col_name} {col_type}")

    # Create indexes
    c.execute('CREATE INDEX IF NOT EXISTS idx_date ON readings(date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_latest_reading_date ON analysis_results(latest_reading_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_analysis_date ON cost_analysis(analysis_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_refill_date ON actual_refill_costs(refill_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_hdd_date ON hdd_data(date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_energy_metrics_analysis_date ON energy_metrics(analysis_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_refill_periods_analysis_date ON refill_periods(analysis_date)')

    conn.commit()
    conn.close()
    print("Database setup completed.")

if __name__ == '__main__':
    setup_database()