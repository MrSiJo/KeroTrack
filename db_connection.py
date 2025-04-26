import sqlite3
from contextlib import contextmanager
import os
from utils.config_loader import load_config, get_config_value

class DatabaseConnection:
    def __init__(self, db_path):
        self.db_path = db_path
        self.connection = None

    def __enter__(self):
        self.connection = sqlite3.connect(self.db_path)
        self.connection.execute('PRAGMA journal_mode=WAL;')
        return self.connection

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.connection:
            self.connection.close()

@contextmanager
def get_db_connection(db_path=None):
    if db_path is None:
        config = load_config()
        db_path = get_config_value(config, 'database', 'path', default='data/KeroTrack_data.db')
    # Ensure the directory exists
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    with DatabaseConnection(db_path) as conn:
        yield conn