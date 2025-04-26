import sqlite3
import os

DB_PATH = 'oil_data.db'
# The first timestamp potentially affected by the bad reading data
START_DATE_TO_DELETE = '2025-03-16 07:30:00' 

def clear_bad_analysis_results():
    """Deletes analysis results from a specific date onwards."""
    conn = None
    deleted_rows = 0

    if not os.path.exists(DB_PATH):
        print(f"Error: Database file not found at {os.path.abspath(DB_PATH)}")
        return

    try:
        print(f"Connecting to database: {DB_PATH}")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Check how many rows will be deleted first (optional but recommended)
        cursor.execute("SELECT COUNT(*) FROM analysis_results WHERE latest_analysis_date >= ?", (START_DATE_TO_DELETE,))
        count = cursor.fetchone()[0]
        print(f"Found {count} analysis results rows to delete (from {START_DATE_TO_DELETE} onwards).")

        if count > 0:
            # Proceed with deletion
            print(f"Attempting to delete analysis results from {START_DATE_TO_DELETE} onwards...")
            sql_delete = "DELETE FROM analysis_results WHERE latest_analysis_date >= ?"
            cursor.execute(sql_delete, (START_DATE_TO_DELETE,))
            deleted_rows = cursor.rowcount
            print(f"- Deleted {deleted_rows} row(s).")

            print("Committing changes to the database...")
            conn.commit()
            print("Changes committed.")
        else:
            print("No rows found matching the deletion criteria. No changes were made.")

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
    print("--- Starting Analysis Results Cleanup Script ---")
    print("IMPORTANT: Ensure you have backed up your database before proceeding.")
    confirm = input(f"Delete all analysis results from {START_DATE_TO_DELETE} onwards? (yes/no): ")
    if confirm.lower() == 'yes':
        clear_bad_analysis_results()
        print("\nReminder: Run 'python oil_analysis.py' next to generate the latest analysis based on corrected data.")
    else:
        print("Aborted. No changes were made.")
    print("--- Analysis Results Cleanup Script Finished ---") 