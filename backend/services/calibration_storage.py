"""
SQLite Storage Service for Kido Calibration Tool
Handles persistence of reference data (ground truth) locally.
"""

import sqlite3
import json
import os
import time
from typing import Dict, List, Any, Optional

# Constants
DB_FILENAME = "calibration.db"
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", DB_FILENAME)

class CalibrationStorage:
    def __init__(self):
        """Initialize the storage service."""
        self._ensure_db_directory()
        self._init_db()

    def _ensure_db_directory(self):
        """Ensure the data directory exists."""
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        """Get a connection to the SQLite database."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initialize the database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Create reference_data table matching the reference implementation
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reference_data (
                key TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                date TEXT,
                hour INTEGER,
                value TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_project_id ON reference_data(project_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_project_date ON reference_data(project_id, date);")
        
        conn.commit()
        conn.close()

    def store_ref_data(self, key: str, value: Any) -> None:
        """
        Store a key-value pair for reference data.
        
        Args:
            key: The unique key (format: refdata:projectId:date:hour)
            value: The data to store (will be JSON serialized)
        """
        # Parse key to extract metadata
        parts = key.split(':')
        # specific format: refdata:projectId:date:hour
        # but we should handle potential variations safely
        project_id = parts[1] if len(parts) > 1 else ""
        date_val = parts[2] if len(parts) > 2 else ""
        hour_val = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
        
        now = int(time.time() * 1000)
        value_str = json.dumps(value)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO reference_data (key, project_id, date, hour, value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
        """, (key, project_id, date_val, hour_val, value_str, now, now))
        
        conn.commit()
        conn.close()

    def get_ref_data(self, key: str) -> Optional[Any]:
        """Retrieve a value by key."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        row = cursor.execute("SELECT value FROM reference_data WHERE key = ?", (key,)).fetchone()
        conn.close()
        
        if row:
            try:
                return json.loads(row['value'])
            except json.JSONDecodeError:
                return None
        return None

    def get_project_ref_data(self, project_id: str) -> List[Any]:
        """Retrieve all reference data for a specific project."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        rows = cursor.execute("SELECT value FROM reference_data WHERE project_id = ?", (project_id,)).fetchall()
        conn.close()
        
        entries = []
        for row in rows:
            try:
                entries.append(json.loads(row['value']))
            except json.JSONDecodeError:
                continue
                
        return entries

    def delete_ref_data(self, key: str) -> bool:
        """Delete a key."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM reference_data WHERE key = ?", (key,))
        rows_affected = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        return rows_affected > 0

# Singleton instance
storage_service = CalibrationStorage()
