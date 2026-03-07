"""
Backup Data Store - PostgreSQL backend (log only, zip files stay on disk)
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from db import get_cursor

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(__file__).parent / "data" / "backups"


class BackupDataStore:
    """Logs backup events in PostgreSQL; zip archives remain on disk."""

    def __init__(self, data_dir=None):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    def log_backup(self, data: dict) -> bool:
        cid = data.get('company_id', 'default')
        try:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO backup_log
                       (company_id, filename, file_path, file_size,
                        backup_type, status, notes, created_by, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (cid,
                     data.get('filename', ''),
                     data.get('file_path', ''),
                     int(data.get('file_size', 0)),
                     data.get('backup_type', 'manual'),
                     data.get('status', 'success'),
                     data.get('notes', ''),
                     data.get('created_by', ''),
                     datetime.utcnow().isoformat())
                )
            return True
        except Exception as e:
            logger.error("log_backup failed: %s", e)
            return False

    def get_backup_history(self, company_id: str = None,
                            limit: int = 50) -> List[dict]:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    "SELECT * FROM backup_log WHERE company_id=%s "
                    "ORDER BY created_at DESC LIMIT %s",
                    (cid, limit)
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_backup_history failed: %s", e)
            return []

    def delete_backup_log(self, record_id: int, company_id: str = None) -> bool:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    "DELETE FROM backup_log WHERE id=%s AND company_id=%s",
                    (record_id, cid)
                )
            return True
        except Exception as e:
            logger.error("delete_backup_log failed: %s", e)
            return False

    def get_backup_file_path(self, filename: str) -> Path:
        return BACKUP_DIR / filename

    def list_backup_files(self) -> List[str]:
        try:
            return [f.name for f in BACKUP_DIR.iterdir() if f.is_file()]
        except Exception:
            return []

    def get_stats(self, company_id: str = None) -> dict:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    """SELECT COUNT(*) AS total,
                       COALESCE(SUM(CASE WHEN status='success' THEN 1 ELSE 0 END), 0) AS successful,
                       COALESCE(SUM(file_size), 0) AS total_size
                       FROM backup_log WHERE company_id=%s""",
                    (cid,)
                )
                row = cur.fetchone()
                return {
                    'total': int(row['total']) if row else 0,
                    'successful': int(row['successful']) if row else 0,
                    'total_size': int(row['total_size']) if row else 0,
                }
        except Exception as e:
            logger.error("get_stats failed: %s", e)
            return {'total': 0, 'successful': 0, 'total_size': 0}


# Singleton
backup_store = BackupDataStore()
