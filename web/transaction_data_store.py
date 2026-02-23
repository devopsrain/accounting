"""
Transaction Data Store

Parquet-based data persistence for transaction management with Excel import/export.
Supports account flagging and individual name detection for transaction review.
"""

import pandas as pd
import numpy as np
import os
import re
import uuid
from datetime import datetime, date
from typing import List, Dict, Optional, Any
import tempfile
import logging

logger = logging.getLogger(__name__)


def _resolve_company_id(company_id=None):
    """Resolve company_id from arg → Flask g → 'default'."""
    if company_id:
        return company_id
    try:
        from flask import g
        return getattr(g, 'company_id', None) or 'default'
    except (ImportError, RuntimeError):
        return 'default'


# Common Ethiopian individual name patterns (first names)
COMMON_INDIVIDUAL_PATTERNS = [
    # Patterns that suggest an individual rather than a business
    r'^\w+\s+\w+$',                       # Two-word names (e.g. "Almaz Tesfaye")
    r'^\w+\s+\w+\s+\w+$',                 # Three-word names (e.g. "Almaz Tesfaye Kebede")
    r'^(Mr|Mrs|Ms|Dr|Ato|W/ro|W/rt)\s',   # Titles (Ethiopian: Ato, W/ro, W/rt)
]

# Keywords that indicate a business/organization entity
BUSINESS_KEYWORDS = [
    'plc', 'pvt', 'ltd', 'llc', 'inc', 'corp', 'co.', 'company', 'group',
    'enterprise', 'trading', 'import', 'export', 'services', 'solutions',
    'bank', 'insurance', 'telecom', 'authority', 'ministry', 'agency',
    'association', 'organization', 'foundation', 'institute', 'university',
    'hotel', 'restaurant', 'pharmacy', 'hospital', 'clinic', 'school',
    'factory', 'manufacturing', 'construction', 'transport', 'logistics',
    'ድርጅት', 'ኃ/የተ/የግ/ማ', 'ኃላ/የተ', 'ባንክ', 'ኢንሹራንስ',
    'share company', 'private limited', 'general trading',
]

# Known system/clearing accounts that should be flagged
FLAGGED_ACCOUNT_PATTERNS = [
    'suspense', 'clearing', 'control', 'intercompany', 'inter-company',
    'adjustment', 'provision', 'accrual', 'accrued', 'prepaid', 'prepayment',
    'receivable', 'payable', 'advance', 'deposit', 'retention',
    'unallocated', 'unidentified', 'miscellaneous', 'misc', 'other',
    'temporary', 'temp', 'transit', 'in-transit',
]


class TransactionDataStore:
    """Data store for transaction management with parquet persistence,
    account flagging and individual name detection"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)

        self.transactions_file = os.path.join(data_dir, "transactions.parquet")
        self.flagged_accounts_file = os.path.join(data_dir, "flagged_accounts.parquet")
        self.import_history_file = os.path.join(data_dir, "transaction_import_history.parquet")

        self.transaction_schema = {
            'id': 'string',
            'company_id': 'string',
            'import_batch_id': 'string',
            'date': 'string',
            'account_code': 'string',
            'account_name': 'string',
            'description': 'string',
            'reference': 'string',
            'counterparty': 'string',
            'debit': 'float64',
            'credit': 'float64',
            'balance': 'float64',
            'currency': 'string',
            'is_flagged': 'bool',
            'flag_reason': 'string',
            'has_individual_name': 'bool',
            'individual_name_field': 'string',
            'review_status': 'string',      # 'pending', 'reviewed', 'approved', 'rejected'
            'reviewer_notes': 'string',
            'created_at': 'string',
        }

        self.flagged_accounts_schema = {
            'id': 'string',
            'account_code': 'string',
            'account_name': 'string',
            'flag_reason': 'string',
            'auto_flagged': 'bool',
            'created_at': 'string',
        }

        self.import_history_schema = {
            'id': 'string',
            'filename': 'string',
            'import_date': 'string',
            'total_rows': 'int64',
            'imported_rows': 'int64',
            'flagged_rows': 'int64',
            'individual_name_rows': 'int64',
            'errors': 'int64',
            'status': 'string',
        }

        self._initialize_files()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def _initialize_files(self):
        for filepath, schema in [
            (self.transactions_file, self.transaction_schema),
            (self.flagged_accounts_file, self.flagged_accounts_schema),
            (self.import_history_file, self.import_history_schema),
        ]:
            if not os.path.exists(filepath):
                df = pd.DataFrame(columns=list(schema.keys()))
                for col, dtype in schema.items():
                    if dtype == 'bool':
                        df[col] = df[col].astype('bool')
                    elif dtype == 'int64':
                        df[col] = pd.array([], dtype='Int64')
                    else:
                        df[col] = df[col].astype(dtype)
                df.to_parquet(filepath, index=False)

    # ------------------------------------------------------------------
    # Name / account detection helpers
    # ------------------------------------------------------------------
    @staticmethod
    def is_individual_name(name: str) -> bool:
        """Detect whether a string looks like an individual person's name
        rather than a business entity."""
        if not name or not isinstance(name, str):
            return False
        name = name.strip()
        if len(name) < 3:
            return False

        name_lower = name.lower()

        # If it contains business keywords → not an individual
        for keyword in BUSINESS_KEYWORDS:
            if keyword in name_lower:
                return False

        # If it matches individual patterns → likely individual
        for pattern in COMMON_INDIVIDUAL_PATTERNS:
            if re.match(pattern, name, re.IGNORECASE):
                # Extra check: names with numbers are likely account codes
                if re.search(r'\d{3,}', name):
                    return False
                return True

        return False

    @staticmethod
    def should_flag_account(account_code: str, account_name: str) -> tuple:
        """Check if an account should be flagged for review.
        Returns (should_flag: bool, reason: str)."""
        if not account_name and not account_code:
            return False, ''

        combined = f"{account_code or ''} {account_name or ''}".lower()

        for pattern in FLAGGED_ACCOUNT_PATTERNS:
            if pattern in combined:
                return True, f"Account contains flagged keyword: '{pattern}'"

        # Flag accounts with no name
        if account_code and not account_name:
            return True, "Account has code but no name"

        return False, ''

    # ------------------------------------------------------------------
    # Transaction CRUD
    # ------------------------------------------------------------------
    def save_transaction(self, txn: Dict[str, Any]) -> bool:
        try:
            df = pd.read_parquet(self.transactions_file)

            if 'id' not in txn or not txn['id']:
                txn['id'] = f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
            if 'created_at' not in txn:
                txn['created_at'] = datetime.now().isoformat()
            if 'review_status' not in txn:
                txn['review_status'] = 'pending'

            # Inject company_id
            txn['company_id'] = txn.get('company_id') or _resolve_company_id()

            # Auto-detect flags
            flagged, reason = self.should_flag_account(
                txn.get('account_code', ''), txn.get('account_name', ''))
            txn.setdefault('is_flagged', flagged)
            if flagged and not txn.get('flag_reason'):
                txn['flag_reason'] = reason

            # Auto-detect individual names across relevant fields
            individual_detected = False
            detected_field = ''
            for field in ['counterparty', 'description', 'account_name']:
                if self.is_individual_name(str(txn.get(field, ''))):
                    individual_detected = True
                    detected_field = field
                    break
            txn.setdefault('has_individual_name', individual_detected)
            txn.setdefault('individual_name_field', detected_field)

            new_row = pd.DataFrame([txn])
            df = pd.concat([df, new_row], ignore_index=True)
            df.to_parquet(self.transactions_file, index=False)
            return True
        except Exception as e:
            print(f"Error saving transaction: {e}")
            return False

    def get_all_transactions(self, company_id: str = None) -> List[Dict[str, Any]]:
        try:
            df = pd.read_parquet(self.transactions_file)
            if 'company_id' not in df.columns:
                df['company_id'] = 'default'
            cid = _resolve_company_id(company_id)
            df = df[df['company_id'] == cid]
            df = df.fillna('')
            return df.to_dict('records')
        except Exception as e:
            print(f"Error loading transactions: {e}")
            return []

    def get_transaction_by_id(self, txn_id: str) -> Optional[Dict[str, Any]]:
        try:
            df = pd.read_parquet(self.transactions_file)
            match = df[df['id'] == txn_id]
            if match.empty:
                return None
            return match.fillna('').iloc[0].to_dict()
        except Exception as e:
            print(f"Error loading transaction: {e}")
            return None

    def update_review_status(self, txn_id: str, status: str, notes: str = '') -> bool:
        try:
            df = pd.read_parquet(self.transactions_file)
            idx = df.index[df['id'] == txn_id]
            if idx.empty:
                return False
            df.loc[idx, 'review_status'] = status
            df.loc[idx, 'reviewer_notes'] = notes
            df.to_parquet(self.transactions_file, index=False)
            return True
        except Exception as e:
            print(f"Error updating review status: {e}")
            return False

    def delete_transaction(self, txn_id: str) -> bool:
        try:
            df = pd.read_parquet(self.transactions_file)
            df = df[df['id'] != txn_id]
            df.to_parquet(self.transactions_file, index=False)
            return True
        except Exception as e:
            print(f"Error deleting transaction: {e}")
            return False

    # ------------------------------------------------------------------
    # Flagged accounts management
    # ------------------------------------------------------------------
    def add_flagged_account(self, account_code: str, account_name: str,
                            reason: str, auto: bool = False) -> bool:
        try:
            df = pd.read_parquet(self.flagged_accounts_file)

            # Avoid duplicates
            if not df[(df['account_code'] == account_code)].empty:
                return True

            row = {
                'id': f"FLAG-{uuid.uuid4().hex[:8]}",
                'account_code': account_code,
                'account_name': account_name,
                'flag_reason': reason,
                'auto_flagged': auto,
                'created_at': datetime.now().isoformat(),
            }
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            df.to_parquet(self.flagged_accounts_file, index=False)
            return True
        except Exception as e:
            print(f"Error adding flagged account: {e}")
            return False

    def get_flagged_accounts(self) -> List[Dict[str, Any]]:
        try:
            df = pd.read_parquet(self.flagged_accounts_file)
            return df.fillna('').to_dict('records')
        except Exception:
            return []

    def remove_flagged_account(self, flag_id: str) -> bool:
        try:
            df = pd.read_parquet(self.flagged_accounts_file)
            df = df[df['id'] != flag_id]
            df.to_parquet(self.flagged_accounts_file, index=False)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Excel import / export
    # ------------------------------------------------------------------
    def import_from_dataframe(self, df: pd.DataFrame, original_filename: str = '') -> Dict[str, Any]:
        """Import transactions from a pandas DataFrame (read by caller).
        Matches the payroll module pattern where pd.read_excel is called in the route.
        Automatically flags accounts and detects individual names."""
        result = {
            'success': False,
            'message': '',
            'total_rows': 0,
            'imported': 0,
            'flagged': 0,
            'individual_names': 0,
            'errors': [],
        }
        batch_id = f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4]}"

        try:
            # Normalise column names to lower-case with underscores
            df.columns = [
                str(c).strip().lower().replace(' ', '_').replace('-', '_')
                for c in df.columns
            ]

            result['total_rows'] = len(df)

            # Column mapping - flexible to handle various excel formats
            col_map = self._build_column_mapping(df.columns.tolist())

            for idx, row in df.iterrows():
                try:
                    txn = {
                        'import_batch_id': batch_id,
                        'date': self._safe_date(row, col_map.get('date')),
                        'account_code': self._safe_str(row, col_map.get('account_code')),
                        'account_name': self._safe_str(row, col_map.get('account_name')),
                        'description': self._safe_str(row, col_map.get('description')),
                        'reference': self._safe_str(row, col_map.get('reference')),
                        'counterparty': self._safe_str(row, col_map.get('counterparty')),
                        'debit': self._safe_float(row, col_map.get('debit')),
                        'credit': self._safe_float(row, col_map.get('credit')),
                        'balance': self._safe_float(row, col_map.get('balance')),
                        'currency': self._safe_str(row, col_map.get('currency')) or 'ETB',
                    }

                    # Run detection
                    flagged, reason = self.should_flag_account(
                        txn['account_code'], txn['account_name'])
                    txn['is_flagged'] = flagged
                    txn['flag_reason'] = reason

                    individual = False
                    ind_field = ''
                    for field in ['counterparty', 'description', 'account_name']:
                        if self.is_individual_name(str(txn.get(field, ''))):
                            individual = True
                            ind_field = field
                            break
                    txn['has_individual_name'] = individual
                    txn['individual_name_field'] = ind_field

                    if self.save_transaction(txn):
                        result['imported'] += 1
                        if flagged:
                            result['flagged'] += 1
                            self.add_flagged_account(
                                txn['account_code'], txn['account_name'], reason, auto=True)
                        if individual:
                            result['individual_names'] += 1
                    else:
                        result['errors'].append(f"Row {idx + 2}: Failed to save")

                except Exception as e:
                    result['errors'].append(f"Row {idx + 2}: {str(e)}")

            result['success'] = True
            result['message'] = (
                f"Imported {result['imported']} of {result['total_rows']} transactions. "
                f"{result['flagged']} flagged accounts, "
                f"{result['individual_names']} with individual names."
            )

            # Save import history
            self._save_import_history(batch_id, original_filename, result)

        except Exception as e:
            result['message'] = f"Import failed: {str(e)}"
            result['errors'].append(str(e))

        return result

    def import_from_excel(self, file_path: str, original_filename: str = '') -> Dict[str, Any]:
        """Import transactions from an Excel file path (legacy method).
        Automatically flags accounts and detects individual names."""
        result = {
            'success': False,
            'message': '',
            'total_rows': 0,
            'imported': 0,
            'flagged': 0,
            'individual_names': 0,
            'errors': [],
        }
        batch_id = f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4]}"

        try:
            sheets = pd.read_excel(file_path, sheet_name=None)

            # Use first sheet if 'Transactions' not found
            sheet_name = 'Transactions' if 'Transactions' in sheets else list(sheets.keys())[0]
            df = sheets[sheet_name]

            # Normalise column names to lower-case with underscores
            df.columns = [
                str(c).strip().lower().replace(' ', '_').replace('-', '_')
                for c in df.columns
            ]

            result['total_rows'] = len(df)

            # Column mapping – flexible to handle various excel formats
            col_map = self._build_column_mapping(df.columns.tolist())

            for idx, row in df.iterrows():
                try:
                    txn = {
                        'import_batch_id': batch_id,
                        'date': self._safe_date(row, col_map.get('date')),
                        'account_code': self._safe_str(row, col_map.get('account_code')),
                        'account_name': self._safe_str(row, col_map.get('account_name')),
                        'description': self._safe_str(row, col_map.get('description')),
                        'reference': self._safe_str(row, col_map.get('reference')),
                        'counterparty': self._safe_str(row, col_map.get('counterparty')),
                        'debit': self._safe_float(row, col_map.get('debit')),
                        'credit': self._safe_float(row, col_map.get('credit')),
                        'balance': self._safe_float(row, col_map.get('balance')),
                        'currency': self._safe_str(row, col_map.get('currency')) or 'ETB',
                    }

                    # Run detection
                    flagged, reason = self.should_flag_account(
                        txn['account_code'], txn['account_name'])
                    txn['is_flagged'] = flagged
                    txn['flag_reason'] = reason

                    individual = False
                    ind_field = ''
                    for field in ['counterparty', 'description', 'account_name']:
                        if self.is_individual_name(str(txn.get(field, ''))):
                            individual = True
                            ind_field = field
                            break
                    txn['has_individual_name'] = individual
                    txn['individual_name_field'] = ind_field

                    if self.save_transaction(txn):
                        result['imported'] += 1
                        if flagged:
                            result['flagged'] += 1
                            self.add_flagged_account(
                                txn['account_code'], txn['account_name'], reason, auto=True)
                        if individual:
                            result['individual_names'] += 1
                    else:
                        result['errors'].append(f"Row {idx + 2}: Failed to save")

                except Exception as e:
                    result['errors'].append(f"Row {idx + 2}: {str(e)}")

            result['success'] = True
            result['message'] = (
                f"Imported {result['imported']} of {result['total_rows']} transactions. "
                f"{result['flagged']} flagged accounts, "
                f"{result['individual_names']} with individual names."
            )

            # Save import history
            self._save_import_history(batch_id, original_filename or file_path, result)

        except Exception as e:
            result['message'] = f"Import failed: {str(e)}"
            result['errors'].append(str(e))

        return result

    def export_to_excel(self, filters: Optional[Dict] = None) -> Optional[str]:
        """Export transactions to Excel with flag/name analysis sheets."""
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
            tmp.close()

            df = pd.read_parquet(self.transactions_file)

            if filters:
                if filters.get('flagged_only'):
                    df = df[df['is_flagged'] == True]
                if filters.get('individual_only'):
                    df = df[df['has_individual_name'] == True]
                if filters.get('review_status'):
                    df = df[df['review_status'] == filters['review_status']]

            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                # All transactions
                df.to_excel(writer, sheet_name='Transactions', index=False)

                # Flagged transactions
                flagged_df = df[df['is_flagged'] == True]
                if not flagged_df.empty:
                    flagged_df.to_excel(writer, sheet_name='Flagged Accounts', index=False)

                # Individual name transactions
                ind_df = df[df['has_individual_name'] == True]
                if not ind_df.empty:
                    ind_df.to_excel(writer, sheet_name='Individual Names', index=False)

                # Summary
                summary = self.get_summary_statistics()
                pd.DataFrame([summary]).to_excel(writer, sheet_name='Summary', index=False)

                # Flagged accounts register
                flagged_accts = pd.read_parquet(self.flagged_accounts_file)
                if not flagged_accts.empty:
                    flagged_accts.to_excel(writer, sheet_name='Flagged Accounts Register', index=False)

            return tmp.name
        except Exception as e:
            print(f"Error exporting to Excel: {e}")
            return None

    def generate_sample_excel(self) -> Optional[str]:
        """Generate a sample/template Excel file for transaction imports."""
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
            tmp.close()

            sample_data = [
                {
                    'Date': '2026-02-01',
                    'Account Code': '1001',
                    'Account Name': 'Cash in Hand',
                    'Description': 'Daily sales collection',
                    'Reference': 'REF-001',
                    'Counterparty': 'Walk-in Customer',
                    'Debit': 15000.00,
                    'Credit': 0.00,
                    'Balance': 15000.00,
                    'Currency': 'ETB',
                },
                {
                    'Date': '2026-02-01',
                    'Account Code': '4001',
                    'Account Name': 'Sales Revenue',
                    'Description': 'Daily sales collection',
                    'Reference': 'REF-001',
                    'Counterparty': 'Walk-in Customer',
                    'Debit': 0.00,
                    'Credit': 15000.00,
                    'Balance': -15000.00,
                    'Currency': 'ETB',
                },
                {
                    'Date': '2026-02-05',
                    'Account Code': '2100',
                    'Account Name': 'Accounts Payable',
                    'Description': 'Payment to supplier',
                    'Reference': 'PAY-002',
                    'Counterparty': 'Almaz Tesfaye',
                    'Debit': 0.00,
                    'Credit': 8500.00,
                    'Balance': -8500.00,
                    'Currency': 'ETB',
                },
                {
                    'Date': '2026-02-10',
                    'Account Code': '9999',
                    'Account Name': 'Suspense Account',
                    'Description': 'Unidentified deposit',
                    'Reference': 'DEP-003',
                    'Counterparty': 'Bekele Mengistu Alemu',
                    'Debit': 25000.00,
                    'Credit': 0.00,
                    'Balance': 25000.00,
                    'Currency': 'ETB',
                },
                {
                    'Date': '2026-02-15',
                    'Account Code': '5010',
                    'Account Name': 'Office Supplies Expense',
                    'Description': 'Stationery purchase',
                    'Reference': 'INV-004',
                    'Counterparty': 'Addis Office Supplies PLC',
                    'Debit': 3200.00,
                    'Credit': 0.00,
                    'Balance': 3200.00,
                    'Currency': 'ETB',
                },
                {
                    'Date': '2026-02-18',
                    'Account Code': '1200',
                    'Account Name': 'Accounts Receivable',
                    'Description': 'Invoice to client',
                    'Reference': 'INV-005',
                    'Counterparty': 'Chaltu Abera Tadesse',
                    'Debit': 45000.00,
                    'Credit': 0.00,
                    'Balance': 45000.00,
                    'Currency': 'ETB',
                },
            ]

            instructions = pd.DataFrame({
                'Column': ['Date', 'Account Code', 'Account Name', 'Description',
                           'Reference', 'Counterparty', 'Debit', 'Credit', 'Balance', 'Currency'],
                'Required': ['Yes', 'Yes', 'Yes', 'No', 'No', 'No', 'Yes', 'Yes', 'No', 'No'],
                'Format': [
                    'YYYY-MM-DD', 'Text (account number)', 'Text (account name)',
                    'Text (transaction detail)', 'Text (reference number)',
                    'Text (customer/supplier name)', 'Number', 'Number', 'Number', 'ETB (default)',
                ],
                'Notes': [
                    'Transaction date', 'Your chart of accounts code',
                    'Account name - flagged if contains suspense/clearing/etc.',
                    'Describes the transaction',
                    'Invoice or receipt number',
                    'Customer or supplier - system detects individual names',
                    'Debit amount (leave 0 if credit)', 'Credit amount (leave 0 if debit)',
                    'Running balance (optional)', 'Defaults to ETB if blank',
                ],
            })

            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                pd.DataFrame(sample_data).to_excel(writer, sheet_name='Transactions', index=False)
                instructions.to_excel(writer, sheet_name='Instructions', index=False)

            return tmp.name
        except Exception as e:
            print(f"Error generating sample Excel: {e}")
            return None

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------
    def get_summary_statistics(self, company_id: str = None) -> Dict[str, Any]:
        try:
            df = pd.read_parquet(self.transactions_file)
            if 'company_id' not in df.columns:
                df['company_id'] = 'default'
            cid = _resolve_company_id(company_id)
            df = df[df['company_id'] == cid]
            if df.empty:
                return {
                    'total_transactions': 0, 'total_debit': 0.0, 'total_credit': 0.0,
                    'net_balance': 0.0, 'flagged_count': 0, 'individual_name_count': 0,
                    'pending_review': 0, 'approved': 0, 'rejected': 0,
                    'unique_accounts': 0, 'import_batches': 0,
                }

            return {
                'total_transactions': len(df),
                'total_debit': float(df['debit'].sum()),
                'total_credit': float(df['credit'].sum()),
                'net_balance': float(df['debit'].sum() - df['credit'].sum()),
                'flagged_count': int(df['is_flagged'].sum()) if 'is_flagged' in df.columns else 0,
                'individual_name_count': int(df['has_individual_name'].sum()) if 'has_individual_name' in df.columns else 0,
                'pending_review': int((df['review_status'] == 'pending').sum()) if 'review_status' in df.columns else 0,
                'approved': int((df['review_status'] == 'approved').sum()) if 'review_status' in df.columns else 0,
                'rejected': int((df['review_status'] == 'rejected').sum()) if 'review_status' in df.columns else 0,
                'unique_accounts': df['account_code'].nunique() if 'account_code' in df.columns else 0,
                'import_batches': df['import_batch_id'].nunique() if 'import_batch_id' in df.columns else 0,
            }
        except Exception as e:
            print(f"Error computing statistics: {e}")
            return {}

    def get_import_history(self) -> List[Dict[str, Any]]:
        try:
            df = pd.read_parquet(self.import_history_file)
            return df.fillna('').to_dict('records')
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _save_import_history(self, batch_id: str, filename: str, result: Dict):
        try:
            df = pd.read_parquet(self.import_history_file)
            row = {
                'id': batch_id,
                'filename': os.path.basename(filename),
                'import_date': datetime.now().isoformat(),
                'total_rows': result.get('total_rows', 0),
                'imported_rows': result.get('imported', 0),
                'flagged_rows': result.get('flagged', 0),
                'individual_name_rows': result.get('individual_names', 0),
                'errors': len(result.get('errors', [])),
                'status': 'success' if result.get('success') else 'failed',
            }
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            df.to_parquet(self.import_history_file, index=False)
        except Exception as e:
            print(f"Error saving import history: {e}")

    @staticmethod
    def _build_column_mapping(columns: List[str]) -> Dict[str, str]:
        """Map common Excel column name variations to our internal names."""
        mapping = {}
        col_aliases = {
            'date': ['date', 'transaction_date', 'txn_date', 'posting_date', 'value_date'],
            'account_code': ['account_code', 'account_no', 'account_number', 'acct_code', 'gl_code', 'code'],
            'account_name': ['account_name', 'account_description', 'acct_name', 'gl_name', 'name'],
            'description': ['description', 'narrative', 'detail', 'details', 'memo', 'narration', 'particulars'],
            'reference': ['reference', 'ref', 'ref_no', 'reference_number', 'document_number', 'doc_no', 'voucher'],
            'counterparty': ['counterparty', 'counter_party', 'customer', 'supplier', 'vendor',
                             'beneficiary', 'payer', 'payee', 'party', 'client', 'client_name', 'supplier_name'],
            'debit': ['debit', 'debit_amount', 'dr', 'dr_amount'],
            'credit': ['credit', 'credit_amount', 'cr', 'cr_amount'],
            'balance': ['balance', 'running_balance', 'cumulative_balance'],
            'currency': ['currency', 'ccy', 'curr'],
        }
        for field, aliases in col_aliases.items():
            for alias in aliases:
                if alias in columns:
                    mapping[field] = alias
                    break
        return mapping

    @staticmethod
    def _safe_str(row, col: Optional[str]) -> str:
        if not col or col not in row.index:
            return ''
        val = row[col]
        if pd.isna(val):
            return ''
        return str(val).strip()

    @staticmethod
    def _safe_float(row, col: Optional[str]) -> float:
        if not col or col not in row.index:
            return 0.0
        val = row[col]
        if pd.isna(val):
            return 0.0
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _safe_date(row, col: Optional[str]) -> str:
        if not col or col not in row.index:
            return datetime.now().strftime('%Y-%m-%d')
        val = row[col]
        if pd.isna(val):
            return datetime.now().strftime('%Y-%m-%d')
        try:
            if isinstance(val, (datetime, date)):
                return val.strftime('%Y-%m-%d')
            return str(val).strip()[:10]
        except Exception:
            return datetime.now().strftime('%Y-%m-%d')

__all__ = ['TransactionDataStore']
