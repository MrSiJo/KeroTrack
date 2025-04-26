import sqlite3
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config_loader import load_config, get_config_value

config = load_config()
DB_PATH = get_config_value(config, 'database', 'path', default='data/KeroTrack_data.db')

def correct_readings():
    """Corrects specific erroneous readings in the database."""
    conn = None
    updated_rows_glitch = 0
    updated_rows_aftermath = 0

    # Check if DB exists
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file not found at {os.path.abspath(DB_PATH)}")
        return

    try:
        print(f"Connecting to database: {DB_PATH}")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # --- Correction for 2025-03-16 07:26:10 --- 
        print("Attempting to correct reading at 2025-03-16 07:26:10...")
        sql_update_glitch = """
            UPDATE readings
            SET 
                litres_remaining = 254.4,
                litres_used_since_last = 0.0,
                percentage_remaining = 20.8,
                oil_depth_cm = 28.0,
                air_gap_cm = 109.0,
                cost_used = '0.00', 
                cost_to_fill = '577.49',
                refill_detected = 'n',
                leak_detected = 'n',
                litres_to_order = 970.6,
                bars_remaining = 2
            WHERE 
                date = '2025-03-16 07:26:10';
        """
        cursor.execute(sql_update_glitch)
        updated_rows_glitch = cursor.rowcount
        print(f"- Corrected {updated_rows_glitch} row(s) for 07:26:10.")

        # --- Correction for 2025-03-16 07:56:07 --- 
        print("Attempting to correct reading at 2025-03-16 07:56:07...")
        sql_update_aftermath = """
            UPDATE readings
            SET 
                litres_used_since_last = 0.4,
                cost_used = '0.24',
                leak_detected = 'n'
            WHERE 
                date = '2025-03-16 07:56:07';
        """
        cursor.execute(sql_update_aftermath)
        updated_rows_aftermath = cursor.rowcount
        print(f"- Corrected {updated_rows_aftermath} row(s) for 07:56:07.")

        # --- Commit changes --- 
        if updated_rows_glitch > 0 or updated_rows_aftermath > 0:
            print("Committing changes to the database...")
            conn.commit()
            print("Changes committed.")
        else:
            print("No rows matched the specified dates. No changes were committed.")

    except sqlite3.Error as e:
        print(f"SQLite error occurred: {e}")
        if conn:
            print("Rolling back changes...")
            conn.rollback()
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        if conn:
            print("Rolling back changes due to unexpected error...")
            conn.rollback()
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    print("--- Starting Database Correction Script ---")
    print("IMPORTANT: Ensure you have backed up your database before proceeding.")
    # Optional: Add a confirmation prompt
    # confirm = input("Do you want to proceed with correcting the readings? (yes/no): ")
    # if confirm.lower() == 'yes':
    correct_readings()
    print("--- Database Correction Script Finished ---")
    print("\nReminder: Run 'python oil_analysis.py' next to update the analysis results based on the corrected data.") 