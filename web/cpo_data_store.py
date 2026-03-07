"""
CPO (Cash Purchase Order) Data Store - PostgreSQL backend
"""

import logging
import uuid
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Any, Optional

from db import get_cursor, get_conn

logger = logging.getLogger(__name__)


class CPODataStore:
    """PostgreSQL-backed CPO management."""

    def __init__(self, data_dir=None):
        pass

    # ------------------------------------------------------------------
    # CPO Records
    # ------------------------------------------------------------------
    def add_cpo(self, data: dict) -> Optional[str]:
        cid = data.get('company_id', 'default')
        cpo_id = data.get('cpo_id') or str(uuid.uuid4())[:8].upper()
        try:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO cpo_records
                       (cpo_id, company_id, cpo_number, vendor_name, vendor_tin,
                        date, delivery_date, item_description, quantity, unit_price,
                        total_amount, vat_amount, withholding_tax, net_payable,
                        payment_method, status, notes, approved_by, created_by, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (cpo_id, company_id) DO NOTHING""",
                    (cpo_id, cid,
                     data.get('cpo_number', ''),
                     data.get('vendor_name', ''),
                     data.get('vendor_tin', ''),
                     data.get('date', str(date.today())),
                     data.get('delivery_date', ''),
                     data.get('item_description', ''),
                     float(data.get('quantity', 1)),
                     float(data.get('unit_price', 0)),
                     float(data.get('total_amount', 0)),
                     float(data.get('vat_amount', 0)),
                     float(data.get('withholding_tax', 0)),
                     float(data.get('net_payable', 0)),
                     data.get('payment_method', 'cash'),
                     data.get('status', 'draft'),
                     data.get('notes', ''),
                     data.get('approved_by', ''),
                     data.get('created_by', ''),
                     datetime.utcnow().isoformat())
                )
            return cpo_id
        except Exception as e:
            logger.error("add_cpo failed: %s", e)
            return None

    def get_cpos(self, company_id: str = None, status: str = None) -> pd.DataFrame:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                if status:
                    cur.execute(
                        "SELECT * FROM cpo_records WHERE company_id=%s AND status=%s "
                        "ORDER BY created_at DESC",
                        (cid, status)
                    )
                else:
                    cur.execute(
                        "SELECT * FROM cpo_records WHERE company_id=%s ORDER BY created_at DESC",
                        (cid,)
                    )
                rows = cur.fetchall()
                return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()
        except Exception as e:
            logger.error("get_cpos failed: %s", e)
            return pd.DataFrame()

    def get_cpo(self, cpo_id: str, company_id: str = None) -> Optional[dict]:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    "SELECT * FROM cpo_records WHERE cpo_id=%s AND company_id=%s",
                    (cpo_id, cid)
                )
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error("get_cpo failed: %s", e)
            return None

    def update_cpo(self, cpo_id: str, data: dict, company_id: str = None) -> bool:
        cid = company_id or data.get('company_id', 'default')
        try:
            with get_cursor() as cur:
                cur.execute(
                    """UPDATE cpo_records SET
                       cpo_number=%s, vendor_name=%s, vendor_tin=%s,
                       date=%s, delivery_date=%s, item_description=%s,
                       quantity=%s, unit_price=%s, total_amount=%s,
                       vat_amount=%s, withholding_tax=%s, net_payable=%s,
                       payment_method=%s, status=%s, notes=%s, approved_by=%s
                       WHERE cpo_id=%s AND company_id=%s""",
                    (data.get('cpo_number', ''),
                     data.get('vendor_name', ''),
                     data.get('vendor_tin', ''),
                     data.get('date', str(date.today())),
                     data.get('delivery_date', ''),
                     data.get('item_description', ''),
                     float(data.get('quantity', 1)),
                     float(data.get('unit_price', 0)),
                     float(data.get('total_amount', 0)),
                     float(data.get('vat_amount', 0)),
                     float(data.get('withholding_tax', 0)),
                     float(data.get('net_payable', 0)),
                     data.get('payment_method', 'cash'),
                     data.get('status', 'draft'),
                     data.get('notes', ''),
                     data.get('approved_by', ''),
                     cpo_id, cid)
                )
            return True
        except Exception as e:
            logger.error("update_cpo failed: %s", e)
            return False

    def delete_cpo(self, cpo_id: str, company_id: str = None) -> bool:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    "DELETE FROM cpo_records WHERE cpo_id=%s AND company_id=%s",
                    (cpo_id, cid)
                )
            return True
        except Exception as e:
            logger.error("delete_cpo failed: %s", e)
            return False

    def bulk_import(self, records: List[Dict], company_id: str = None) -> dict:
        result = {'imported': 0, 'errors': []}
        cid = company_id or 'default'
        imported_at = datetime.utcnow().isoformat()
        for r in records:
            r['company_id'] = cid
            cpo_id = self.add_cpo(r)
            if cpo_id:
                result['imported'] += 1
            else:
                result['errors'].append(f"Failed: {r.get('cpo_number','')}")
        try:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO cpo_import_history
                       (company_id, imported_at, record_count, status)
                       VALUES (%s,%s,%s,%s)""",
                    (cid, imported_at, result['imported'], 'completed')
                )
        except Exception:
            pass
        return result

    def get_import_history(self, company_id: str = None) -> List[dict]:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    "SELECT * FROM cpo_import_history WHERE company_id=%s "
                    "ORDER BY imported_at DESC LIMIT 100",
                    (cid,)
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_import_history failed: %s", e)
            return []

    def get_stats(self, company_id: str = None) -> dict:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    """SELECT status, COUNT(*) AS cnt,
                       COALESCE(SUM(net_payable),0) AS total
                       FROM cpo_records WHERE company_id=%s GROUP BY status""",
                    (cid,)
                )
                stats = {'total': 0, 'total_value': 0.0, 'by_status': {}}
                for row in cur.fetchall():
                    stats['by_status'][row['status']] = {
                        'count': row['cnt'],
                        'value': float(row['total'])
                    }
                    stats['total'] += row['cnt']
                    stats['total_value'] += float(row['total'])
                return stats
        except Exception as e:
            logger.error("get_stats failed: %s", e)
            return {'total': 0, 'total_value': 0.0, 'by_status': {}}


# Singleton
cpo_store = CPODataStore()
