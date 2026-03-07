"""
VAT Data Store - PostgreSQL backend
"""

import logging
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Any, Optional

from db import get_cursor, get_conn

logger = logging.getLogger(__name__)


class VATDataStore:
    """PostgreSQL-backed VAT data store for income, expenses, and capital."""

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # income
    # ------------------------------------------------------------------
    def add_income(self, data: dict) -> bool:
        cid = data.get('company_id', 'default')
        try:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO vat_income
                       (company_id, tax_period, description, amount,
                        vat_rate, vat_amount, taxable_income, invoice_number,
                        customer_name, status, created_by, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (cid,
                     data.get('tax_period', str(date.today())[:7]),
                     data.get('description', ''),
                     float(data.get('amount', 0)),
                     float(data.get('vat_rate', 15.0)),
                     float(data.get('vat_amount', 0)),
                     float(data.get('taxable_income', 0)),
                     data.get('invoice_number', ''),
                     data.get('customer_name', ''),
                     data.get('status', 'active'),
                     data.get('created_by', ''),
                     datetime.utcnow().isoformat())
                )
            return True
        except Exception as e:
            logger.error("add_income failed: %s", e)
            return False

    def get_income(self, company_id: str = None, tax_period: str = None) -> List[dict]:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                if tax_period:
                    cur.execute(
                        "SELECT * FROM vat_income WHERE company_id=%s AND tax_period=%s "
                        "ORDER BY created_at DESC",
                        (cid, tax_period)
                    )
                else:
                    cur.execute(
                        "SELECT * FROM vat_income WHERE company_id=%s ORDER BY created_at DESC",
                        (cid,)
                    )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_income failed: %s", e)
            return []

    def delete_income(self, record_id: int, company_id: str = None) -> bool:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    "DELETE FROM vat_income WHERE id=%s AND company_id=%s",
                    (record_id, cid)
                )
            return True
        except Exception as e:
            logger.error("delete_income failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # expenses
    # ------------------------------------------------------------------
    def add_expense(self, data: dict) -> bool:
        cid = data.get('company_id', 'default')
        try:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO vat_expenses
                       (company_id, tax_period, description, amount,
                        vat_rate, vat_amount, vendor_name, invoice_number,
                        category, status, created_by, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (cid,
                     data.get('tax_period', str(date.today())[:7]),
                     data.get('description', ''),
                     float(data.get('amount', 0)),
                     float(data.get('vat_rate', 15.0)),
                     float(data.get('vat_amount', 0)),
                     data.get('vendor_name', ''),
                     data.get('invoice_number', ''),
                     data.get('category', ''),
                     data.get('status', 'active'),
                     data.get('created_by', ''),
                     datetime.utcnow().isoformat())
                )
            return True
        except Exception as e:
            logger.error("add_expense failed: %s", e)
            return False

    def get_expenses(self, company_id: str = None, tax_period: str = None) -> List[dict]:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                if tax_period:
                    cur.execute(
                        "SELECT * FROM vat_expenses WHERE company_id=%s AND tax_period=%s "
                        "ORDER BY created_at DESC",
                        (cid, tax_period)
                    )
                else:
                    cur.execute(
                        "SELECT * FROM vat_expenses WHERE company_id=%s ORDER BY created_at DESC",
                        (cid,)
                    )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_expenses failed: %s", e)
            return []

    def delete_expense(self, record_id: int, company_id: str = None) -> bool:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    "DELETE FROM vat_expenses WHERE id=%s AND company_id=%s",
                    (record_id, cid)
                )
            return True
        except Exception as e:
            logger.error("delete_expense failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # capital
    # ------------------------------------------------------------------
    def add_capital(self, data: dict) -> bool:
        cid = data.get('company_id', 'default')
        try:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO vat_capital
                       (company_id, tax_period, description, amount,
                        vat_amount, asset_type, useful_life_years,
                        created_by, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (cid,
                     data.get('tax_period', str(date.today())[:7]),
                     data.get('description', ''),
                     float(data.get('amount', 0)),
                     float(data.get('vat_amount', 0)),
                     data.get('asset_type', ''),
                     int(data.get('useful_life_years', 5)),
                     data.get('created_by', ''),
                     datetime.utcnow().isoformat())
                )
            return True
        except Exception as e:
            logger.error("add_capital failed: %s", e)
            return False

    def get_capital(self, company_id: str = None, tax_period: str = None) -> List[dict]:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                if tax_period:
                    cur.execute(
                        "SELECT * FROM vat_capital WHERE company_id=%s AND tax_period=%s "
                        "ORDER BY created_at DESC",
                        (cid, tax_period)
                    )
                else:
                    cur.execute(
                        "SELECT * FROM vat_capital WHERE company_id=%s ORDER BY created_at DESC",
                        (cid,)
                    )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_capital failed: %s", e)
            return []

    def delete_capital(self, record_id: int, company_id: str = None) -> bool:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                cur.execute(
                    "DELETE FROM vat_capital WHERE id=%s AND company_id=%s",
                    (record_id, cid)
                )
            return True
        except Exception as e:
            logger.error("delete_capital failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # summary
    # ------------------------------------------------------------------
    def get_vat_summary(self, company_id: str = None, tax_period: str = None) -> dict:
        cid = company_id or 'default'
        try:
            with get_cursor() as cur:
                if tax_period:
                    cur.execute(
                        "SELECT COALESCE(SUM(vat_amount),0) FROM vat_income "
                        "WHERE company_id=%s AND tax_period=%s",
                        (cid, tax_period)
                    )
                else:
                    cur.execute(
                        "SELECT COALESCE(SUM(vat_amount),0) FROM vat_income WHERE company_id=%s",
                        (cid,)
                    )
                output_vat = float(cur.fetchone()['coalesce'])

                if tax_period:
                    cur.execute(
                        "SELECT COALESCE(SUM(vat_amount),0) FROM vat_expenses "
                        "WHERE company_id=%s AND tax_period=%s",
                        (cid, tax_period)
                    )
                else:
                    cur.execute(
                        "SELECT COALESCE(SUM(vat_amount),0) FROM vat_expenses WHERE company_id=%s",
                        (cid,)
                    )
                input_vat = float(cur.fetchone()['coalesce'])

                net = output_vat - input_vat
                return {
                    'output_vat': output_vat,
                    'input_vat': input_vat,
                    'net_vat': net,
                    'payable': max(0, net),
                    'refundable': max(0, -net),
                }
        except Exception as e:
            logger.error("get_vat_summary failed: %s", e)
            return {'output_vat': 0, 'input_vat': 0, 'net_vat': 0, 'payable': 0, 'refundable': 0}


# Singleton
vat_store = VATDataStore()
