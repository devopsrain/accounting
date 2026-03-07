"""
Transaction Data Store - PostgreSQL backend
"""

import logging
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Any, Optional

from db import get_cursor, get_conn, get_tenant_cursor

logger = logging.getLogger(__name__)


class TransactionDataStore:
    """PostgreSQL-backed transaction store."""

    def __init__(self, data_dir=None):
        pass

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------
    def add_transaction(self, data: dict) -> bool:
        cid = data.get('company_id', 'default')
        try:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO transactions
                       (company_id, date, description, debit_account, credit_account,
                        amount, reference, category, status, created_by, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (cid,
                     data.get('date', str(date.today())),
                     data.get('description', ''),
                     data.get('debit_account', ''),
                     data.get('credit_account', ''),
                     float(data.get('amount', 0)),
                     data.get('reference', ''),
                     data.get('category', ''),
                     data.get('status', 'active'),
                     data.get('created_by', ''),
                     datetime.utcnow().isoformat())
                )
            return True
        except Exception as e:
            logger.error("add_transaction failed: %s", e)
            return False

    def get_transactions(self, company_id: str = None, start_date: str = None,
                         end_date: str = None) -> pd.DataFrame:
        cid = company_id or 'default'
        try:
            with get_tenant_cursor(cid) as cur:
                sql = "SELECT * FROM transactions WHERE company_id=%s"
                params = [cid]
                if start_date:
                    sql += " AND date >= %s"
                    params.append(start_date)
                if end_date:
                    sql += " AND date <= %s"
                    params.append(end_date)
                sql += " ORDER BY date DESC LIMIT 1000"
                cur.execute(sql, params)
                rows = cur.fetchall()
                return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()
        except Exception as e:
            logger.error("get_transactions failed: %s", e)
            return pd.DataFrame()

    def delete_transaction(self, record_id: int, company_id: str = None) -> bool:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    "DELETE FROM transactions WHERE id=%s AND company_id=%s",
                    (record_id, cid)
                )
            return True
        except Exception as e:
            logger.error("delete_transaction failed: %s", e)
            return False

    def bulk_import(self, records: List[Dict], company_id: str = None) -> dict:
        result = {'imported': 0, 'errors': []}
        cid = company_id or 'default'
        imported_at = datetime.utcnow().isoformat()
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    for r in records:
                        r['company_id'] = cid
                        try:
                            cur.execute(
                                """INSERT INTO transactions
                                   (company_id, date, description, debit_account,
                                    credit_account, amount, reference, category,
                                    status, created_by, created_at)
                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                (cid,
                                 r.get('date', str(date.today())),
                                 r.get('description', ''),
                                 r.get('debit_account', ''),
                                 r.get('credit_account', ''),
                                 float(r.get('amount', 0)),
                                 r.get('reference', ''),
                                 r.get('category', ''),
                                 'active',
                                 r.get('created_by', ''),
                                 imported_at)
                            )
                            result['imported'] += 1
                        except Exception as e:
                            result['errors'].append(str(e))
                    # log import history
                    cur.execute(
                        """INSERT INTO transaction_import_history
                           (company_id, imported_at, record_count, status)
                           VALUES (%s,%s,%s,%s)""",
                        (cid, imported_at, result['imported'], 'completed')
                    )
        except Exception as e:
            result['errors'].append(str(e))
        return result

    # ------------------------------------------------------------------
    # Flagged accounts
    # ------------------------------------------------------------------
    def flag_account(self, data: dict) -> bool:
        cid = data.get('company_id', 'default')
        try:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO flagged_accounts
                       (company_id, account_code, account_name, reason,
                        flagged_by, flagged_at)
                       VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (company_id, account_code) DO UPDATE
                       SET reason=%s, flagged_by=%s, flagged_at=%s""",
                    (cid,
                     data.get('account_code', ''),
                     data.get('account_name', ''),
                     data.get('reason', ''),
                     data.get('flagged_by', ''),
                     datetime.utcnow().isoformat(),
                     data.get('reason', ''),
                     data.get('flagged_by', ''),
                     datetime.utcnow().isoformat())
                )
            return True
        except Exception as e:
            logger.error("flag_account failed: %s", e)
            return False

    def get_flagged_accounts(self, company_id: str = None) -> pd.DataFrame:
        cid = company_id or 'default'
        try:
            with get_tenant_cursor(cid) as cur:
                cur.execute(
                    "SELECT * FROM flagged_accounts WHERE company_id=%s ORDER BY flagged_at DESC",
                    (cid,)
                )
                rows = cur.fetchall()
                return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()
        except Exception as e:
            logger.error("get_flagged_accounts failed: %s", e)
            return pd.DataFrame()

    def unflag_account(self, account_code: str, company_id: str = None) -> bool:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    "DELETE FROM flagged_accounts WHERE company_id=%s AND account_code=%s",
                    (cid, account_code)
                )
            return True
        except Exception as e:
            logger.error("unflag_account failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Import history
    # ------------------------------------------------------------------
    def get_import_history(self, company_id: str = None) -> List[dict]:
        cid = company_id or 'default'
        try:
            with get_tenant_cursor(cid) as cur:
                cur.execute(
                    "SELECT * FROM transaction_import_history WHERE company_id=%s "
                    "ORDER BY imported_at DESC LIMIT 100",
                    (cid,)
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_import_history failed: %s", e)
            return []


# Singleton
transaction_store = TransactionDataStore()
