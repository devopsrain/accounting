"""
CPO (Cash Payment Order) Data Store

Parquet-based data persistence for CPO records with Excel import/export.
Fields: name, date, amount, bid_name
"""

import pandas as pd
import os
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


class CPODataStore:
    """Data store for Cash Payment Orders with parquet persistence."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)

        self.cpo_file = os.path.join(data_dir, "cpo_records.parquet")
        self.import_history_file = os.path.join(data_dir, "cpo_import_history.parquet")

        self.cpo_schema = {
            'id': 'string',
            'company_id': 'string',
            'import_batch_id': 'string',
            'name': 'string',
            'date': 'string',
            'amount': 'float64',
            'bid_name': 'string',
            'is_returned': 'string',
            'returned_date': 'string',
            'created_at': 'string',
        }

        self.import_history_schema = {
            'id': 'string',
            'filename': 'string',
            'import_date': 'string',
            'total_rows': 'int64',
            'imported_rows': 'int64',
            'errors': 'int64',
            'status': 'string',
        }

        self._initialize_files()

    def _initialize_files(self):
        for filepath, schema in [
            (self.cpo_file, self.cpo_schema),
            (self.import_history_file, self.import_history_schema),
        ]:
            if not os.path.exists(filepath):
                df = pd.DataFrame(columns=list(schema.keys()))
                for col, dtype in schema.items():
                    if dtype == 'int64':
                        df[col] = pd.array([], dtype='Int64')
                    else:
                        df[col] = df[col].astype(dtype)
                df.to_parquet(filepath, index=False)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def save_cpo(self, record: Dict[str, Any]) -> bool:
        try:
            df = pd.read_parquet(self.cpo_file)

            if 'id' not in record or not record['id']:
                record['id'] = f"CPO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
            if 'created_at' not in record:
                record['created_at'] = datetime.now().isoformat()

            # Inject company_id
            record['company_id'] = record.get('company_id') or _resolve_company_id()

            new_row = pd.DataFrame([record])
            df = pd.concat([df, new_row], ignore_index=True)
            df.to_parquet(self.cpo_file, index=False)
            return True
        except Exception as e:
            print(f"Error saving CPO: {e}")
            return False

    def update_cpo(self, cpo_id: str, updates: Dict[str, Any]) -> bool:
        """Update an existing CPO record by ID."""
        try:
            df = pd.read_parquet(self.cpo_file)
            mask = df['id'] == cpo_id
            if not mask.any():
                return False
            for key, value in updates.items():
                if key in df.columns:
                    df.loc[mask, key] = value
                elif key not in ('id',):
                    df[key] = ''
                    df.loc[mask, key] = value
            df.to_parquet(self.cpo_file, index=False)
            return True
        except Exception as e:
            print(f"Error updating CPO: {e}")
            return False

    def get_all_cpos(self, company_id: str = None) -> List[Dict[str, Any]]:
        try:
            df = pd.read_parquet(self.cpo_file)
            # Ensure new columns exist for older parquet files
            for col in ('is_returned', 'returned_date'):
                if col not in df.columns:
                    df[col] = ''
            if 'company_id' not in df.columns:
                df['company_id'] = 'default'
            cid = _resolve_company_id(company_id)
            df = df[df['company_id'] == cid]
            df = df.fillna('')
            return df.to_dict('records')
        except Exception as e:
            print(f"Error loading CPOs: {e}")
            return []

    def get_cpo_by_id(self, cpo_id: str) -> Optional[Dict[str, Any]]:
        try:
            df = pd.read_parquet(self.cpo_file)
            # Ensure new columns exist for older parquet files
            for col in ('is_returned', 'returned_date'):
                if col not in df.columns:
                    df[col] = ''
            match = df[df['id'] == cpo_id]
            if match.empty:
                return None
            return match.fillna('').iloc[0].to_dict()
        except Exception:
            return None

    def delete_cpo(self, cpo_id: str) -> bool:
        try:
            df = pd.read_parquet(self.cpo_file)
            df = df[df['id'] != cpo_id]
            df.to_parquet(self.cpo_file, index=False)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Import from DataFrame (payroll-style: caller does pd.read_excel)
    # ------------------------------------------------------------------
    def import_from_dataframe(self, df: pd.DataFrame, original_filename: str = '') -> Dict[str, Any]:
        """Import CPO records from a DataFrame."""
        result = {
            'success': False,
            'message': '',
            'total_rows': 0,
            'imported': 0,
            'errors': [],
        }
        batch_id = f"CPO-BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4]}"

        try:
            # Normalise column names
            df.columns = [
                str(c).strip().lower().replace(' ', '_').replace('-', '_')
                for c in df.columns
            ]

            result['total_rows'] = len(df)
            col_map = self._build_column_mapping(df.columns.tolist())

            for idx, row in df.iterrows():
                try:
                    is_returned_val = self._safe_str(row, col_map.get('is_returned')).lower()
                    is_returned = 'Yes' if is_returned_val in ('yes', 'true', '1', 'returned') else 'No'
                    returned_date = self._safe_date_optional(row, col_map.get('returned_date')) if is_returned == 'Yes' else ''

                    record = {
                        'import_batch_id': batch_id,
                        'name': self._safe_str(row, col_map.get('name')),
                        'date': self._safe_date(row, col_map.get('date')),
                        'amount': self._safe_float(row, col_map.get('amount')),
                        'bid_name': self._safe_str(row, col_map.get('bid_name')),
                        'is_returned': is_returned,
                        'returned_date': returned_date,
                    }

                    # Skip rows with no name and no amount
                    if not record['name'] and record['amount'] == 0.0:
                        result['errors'].append(f"Row {idx + 2}: Empty row skipped")
                        continue

                    if self.save_cpo(record):
                        result['imported'] += 1
                    else:
                        result['errors'].append(f"Row {idx + 2}: Failed to save")

                except Exception as e:
                    result['errors'].append(f"Row {idx + 2}: {str(e)}")

            result['success'] = True
            result['message'] = f"Imported {result['imported']} of {result['total_rows']} CPO records."

            self._save_import_history(batch_id, original_filename, result)

        except Exception as e:
            result['message'] = f"Import failed: {str(e)}"
            result['errors'].append(str(e))

        return result

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_to_excel(self) -> Optional[str]:
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
            tmp.close()

            df = pd.read_parquet(self.cpo_file)

            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                # Rename columns for clean export
                # Ensure new columns exist for older parquet files
                for col in ('is_returned', 'returned_date'):
                    if col not in df.columns:
                        df[col] = ''
                export_df = df[['name', 'date', 'amount', 'bid_name', 'is_returned', 'returned_date']].copy()
                export_df.columns = ['Name', 'Date', 'Amount', 'Bid Name', 'Returned', 'Returned Date']
                export_df.to_excel(writer, sheet_name='CPO Records', index=False)

                # Summary
                summary = self.get_summary()
                pd.DataFrame([summary]).to_excel(writer, sheet_name='Summary', index=False)

            return tmp.name
        except Exception as e:
            print(f"Error exporting CPO to Excel: {e}")
            return None

    def generate_sample_excel(self) -> Optional[str]:
        """Generate a sample/template Excel file for CPO imports."""
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
            tmp.close()

            sample_data = [
                {'Name': 'Abebe Kebede', 'Date': '2026-02-01', 'Amount': 50000.00, 'Bid Name': 'Road Construction Phase 1', 'Returned': 'Yes', 'Returned Date': '2026-02-10'},
                {'Name': 'Tigist Haile', 'Date': '2026-02-05', 'Amount': 125000.00, 'Bid Name': 'Office Furniture Supply', 'Returned': 'No', 'Returned Date': ''},
                {'Name': 'Dawit Mekonnen', 'Date': '2026-02-10', 'Amount': 78000.00, 'Bid Name': 'IT Equipment Procurement', 'Returned': 'Yes', 'Returned Date': '2026-02-18'},
                {'Name': 'Sara Alemu', 'Date': '2026-02-15', 'Amount': 200000.00, 'Bid Name': 'Building Renovation', 'Returned': 'No', 'Returned Date': ''},
                {'Name': 'Yonas Tadesse', 'Date': '2026-02-18', 'Amount': 35000.00, 'Bid Name': 'Consulting Services', 'Returned': 'Yes', 'Returned Date': '2026-02-20'},
            ]

            instructions = pd.DataFrame({
                'Column': ['Name', 'Date', 'Amount', 'Bid Name', 'Returned', 'Returned Date'],
                'Required': ['Yes', 'Yes', 'Yes', 'Yes', 'No', 'If Returned=Yes'],
                'Format': ['Text', 'YYYY-MM-DD', 'Number', 'Text', 'Yes/No', 'YYYY-MM-DD'],
                'Notes': [
                    'Payee / recipient name',
                    'Payment date',
                    'Payment amount in ETB',
                    'Name of the bid or project',
                    'Whether the CPO has been returned (Yes or No)',
                    'Date when the CPO was returned (required if Returned = Yes)',
                ],
            })

            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                pd.DataFrame(sample_data).to_excel(writer, sheet_name='CPO Records', index=False)
                instructions.to_excel(writer, sheet_name='Instructions', index=False)

            return tmp.name
        except Exception as e:
            print(f"Error generating CPO sample: {e}")
            return None

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------
    def get_summary(self, company_id: str = None) -> Dict[str, Any]:
        try:
            df = pd.read_parquet(self.cpo_file)
            # Ensure new columns exist for older parquet files
            for col in ('is_returned', 'returned_date'):
                if col not in df.columns:
                    df[col] = ''
            if 'company_id' not in df.columns:
                df['company_id'] = 'default'
            cid = _resolve_company_id(company_id)
            df = df[df['company_id'] == cid]
            if df.empty:
                return {'total_records': 0, 'total_amount': 0.0, 'unique_names': 0, 'unique_bids': 0, 'returned_count': 0, 'not_returned_count': 0}

            returned = df['is_returned'].str.lower().isin(['yes', 'true', '1'])
            return {
                'total_records': len(df),
                'total_amount': float(df['amount'].sum()),
                'unique_names': df['name'].nunique(),
                'unique_bids': df['bid_name'].nunique(),
                'returned_count': int(returned.sum()),
                'not_returned_count': int((~returned).sum()),
            }
        except Exception:
            return {'total_records': 0, 'total_amount': 0.0, 'unique_names': 0, 'unique_bids': 0, 'returned_count': 0, 'not_returned_count': 0}

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
                'errors': len(result.get('errors', [])),
                'status': 'success' if result.get('success') else 'failed',
            }
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            df.to_parquet(self.import_history_file, index=False)
        except Exception as e:
            print(f"Error saving CPO import history: {e}")

    @staticmethod
    def _build_column_mapping(columns: List[str]) -> Dict[str, str]:
        mapping = {}
        col_aliases = {
            'name': ['name', 'payee', 'recipient', 'payee_name', 'recipient_name', 'vendor', 'supplier'],
            'date': ['date', 'payment_date', 'cpo_date', 'order_date', 'txn_date'],
            'amount': ['amount', 'payment_amount', 'total', 'total_amount', 'value', 'sum'],
            'bid_name': ['bid_name', 'bid', 'project', 'project_name', 'tender', 'tender_name', 'description', 'purpose'],
            'is_returned': ['is_returned', 'returned', 'cpo_returned', 'return_status'],
            'returned_date': ['returned_date', 'return_date', 'date_returned'],
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

    @staticmethod
    def _safe_date_optional(row, col: Optional[str]) -> str:
        """Like _safe_date but returns '' instead of today when missing."""
        if not col or col not in row.index:
            return ''
        val = row[col]
        if pd.isna(val):
            return ''
        try:
            if isinstance(val, (datetime, date)):
                return val.strftime('%Y-%m-%d')
            s = str(val).strip()[:10]
            return s if s else ''
        except Exception:
            return ''

__all__ = ['CPODataStore']
