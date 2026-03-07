"""
Bid Data Store - PostgreSQL backend
"""

import logging
import uuid
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Any, Optional

from db import get_cursor, get_conn

logger = logging.getLogger(__name__)


class BidDataStore:
    """PostgreSQL-backed bid/tender management."""

    def __init__(self, data_dir=None):
        pass

    # ------------------------------------------------------------------
    # Bids
    # ------------------------------------------------------------------
    def add_bid(self, data: dict) -> Optional[str]:
        cid = data.get('company_id', 'default')
        bid_id = data.get('bid_id') or str(uuid.uuid4())[:8].upper()
        try:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO bid_records
                       (bid_id, company_id, title, client_name, bid_number,
                        submission_date, opening_date, estimated_value, bid_value,
                        status, category, description, notes, created_by, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (bid_id, company_id) DO NOTHING""",
                    (bid_id, cid,
                     data.get('title', ''),
                     data.get('client_name', ''),
                     data.get('bid_number', ''),
                     data.get('submission_date', str(date.today())),
                     data.get('opening_date', ''),
                     float(data.get('estimated_value', 0)),
                     float(data.get('bid_value', 0)),
                     data.get('status', 'draft'),
                     data.get('category', ''),
                     data.get('description', ''),
                     data.get('notes', ''),
                     data.get('created_by', ''),
                     datetime.utcnow().isoformat())
                )
            return bid_id
        except Exception as e:
            logger.error("add_bid failed: %s", e)
            return None

    def get_bids(self, company_id: str = None, status: str = None) -> pd.DataFrame:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                if status:
                    cur.execute(
                        "SELECT * FROM bid_records WHERE company_id=%s AND status=%s "
                        "ORDER BY created_at DESC",
                        (cid, status)
                    )
                else:
                    cur.execute(
                        "SELECT * FROM bid_records WHERE company_id=%s ORDER BY created_at DESC",
                        (cid,)
                    )
                rows = cur.fetchall()
                return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()
        except Exception as e:
            logger.error("get_bids failed: %s", e)
            return pd.DataFrame()

    def get_bid(self, bid_id: str, company_id: str = None) -> Optional[dict]:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    "SELECT * FROM bid_records WHERE bid_id=%s AND company_id=%s",
                    (bid_id, cid)
                )
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error("get_bid failed: %s", e)
            return None

    def update_bid(self, bid_id: str, data: dict, company_id: str = None) -> bool:
        cid = company_id or data.get('company_id', 'default')
        try:
            with get_cursor() as cur:
                cur.execute(
                    """UPDATE bid_records SET
                       title=%s, client_name=%s, bid_number=%s,
                       submission_date=%s, opening_date=%s,
                       estimated_value=%s, bid_value=%s, status=%s,
                       category=%s, description=%s, notes=%s
                       WHERE bid_id=%s AND company_id=%s""",
                    (data.get('title', ''),
                     data.get('client_name', ''),
                     data.get('bid_number', ''),
                     data.get('submission_date', str(date.today())),
                     data.get('opening_date', ''),
                     float(data.get('estimated_value', 0)),
                     float(data.get('bid_value', 0)),
                     data.get('status', 'draft'),
                     data.get('category', ''),
                     data.get('description', ''),
                     data.get('notes', ''),
                     bid_id, cid)
                )
            return True
        except Exception as e:
            logger.error("update_bid failed: %s", e)
            return False

    def delete_bid(self, bid_id: str, company_id: str = None) -> bool:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    "DELETE FROM bid_records WHERE bid_id=%s AND company_id=%s",
                    (bid_id, cid)
                )
            return True
        except Exception as e:
            logger.error("delete_bid failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Documents (metadata only  files stay on disk)
    # ------------------------------------------------------------------
    def add_document_meta(self, bid_id: str, data: dict,
                           company_id: str = None) -> bool:
        cid = company_id or data.get('company_id', 'default')
        try:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO bid_documents_meta
                       (bid_id, company_id, filename, original_name,
                        file_size, doc_type, uploaded_by, uploaded_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (bid_id, cid,
                     data.get('filename', ''),
                     data.get('original_name', ''),
                     int(data.get('file_size', 0)),
                     data.get('doc_type', 'general'),
                     data.get('uploaded_by', ''),
                     datetime.utcnow().isoformat())
                )
            return True
        except Exception as e:
            logger.error("add_document_meta failed: %s", e)
            return False

    def get_documents(self, bid_id: str, company_id: str = None) -> List[dict]:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    "SELECT * FROM bid_documents_meta WHERE bid_id=%s AND company_id=%s "
                    "ORDER BY uploaded_at DESC",
                    (bid_id, cid)
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_documents failed: %s", e)
            return []

    def get_stats(self, company_id: str = None) -> dict:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    """SELECT status, COUNT(*) AS cnt, COALESCE(SUM(bid_value),0) AS total
                       FROM bid_records WHERE company_id=%s GROUP BY status""",
                    (cid,)
                )
                stats = {'total': 0, 'by_status': {}}
                for row in cur.fetchall():
                    stats['by_status'][row['status']] = {
                        'count': row['cnt'],
                        'value': float(row['total'])
                    }
                    stats['total'] += row['cnt']
                return stats
        except Exception as e:
            logger.error("get_stats failed: %s", e)
            return {'total': 0, 'by_status': {}}


# Singleton
bid_store = BidDataStore()
