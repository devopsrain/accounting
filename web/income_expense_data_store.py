"""
Income & Expense Data Store

Parquet-based data persistence for income and expense management with Excel import/export functionality
"""

import pandas as pd
import os
from datetime import datetime, date
from decimal import Decimal
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


class IncomeExpenseDataStore:
    """Data store for income and expense management with parquet persistence"""
    
    def __init__(self, data_dir: str = "data"):
        """Initialize data store with parquet files"""
        self.data_dir = data_dir
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            
        self.income_file = os.path.join(data_dir, "income_records.parquet")
        self.expense_file = os.path.join(data_dir, "expense_records.parquet")
        
        # Define schemas
        self.income_schema = {
            'id': 'string',
            'company_id': 'string',
            'date': 'string',
            'description': 'string',
            'category': 'string',
            'client_name': 'string',
            'client_tin': 'string',
            'gross_amount': 'float64',
            'tax_rate': 'float64',
            'tax_amount': 'float64',
            'net_amount': 'float64',
            'payment_method': 'string',
            'reference_number': 'string',
            'created_at': 'string'
        }
        
        self.expense_schema = {
            'id': 'string',
            'company_id': 'string',
            'date': 'string',
            'description': 'string',
            'category': 'string',
            'supplier_name': 'string',
            'supplier_tin': 'string',
            'gross_amount': 'float64',
            'tax_rate': 'float64',
            'tax_amount': 'float64',
            'net_amount': 'float64',
            'payment_method': 'string',
            'receipt_number': 'string',
            'is_deductible': 'bool',
            'created_at': 'string'
        }
        
        # Initialize empty files if they don't exist
        self._initialize_files()
    
    def _initialize_files(self):
        """Initialize empty parquet files if they don't exist"""
        if not os.path.exists(self.income_file):
            empty_income = pd.DataFrame(columns=list(self.income_schema.keys()))
            empty_income = empty_income.astype(self.income_schema)
            empty_income.to_parquet(self.income_file, index=False)
            
        if not os.path.exists(self.expense_file):
            empty_expense = pd.DataFrame(columns=list(self.expense_schema.keys()))
            empty_expense = empty_expense.astype(self.expense_schema)
            empty_expense.to_parquet(self.expense_file, index=False)
    
    def save_income_record(self, income_data: Dict[str, Any]) -> bool:
        """Save income record to parquet file"""
        try:
            # Generate ID if not provided
            if 'id' not in income_data:
                income_data['id'] = f"INC_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Add created timestamp
            income_data['created_at'] = datetime.now().isoformat()
            
            # Inject company_id
            income_data['company_id'] = income_data.get('company_id') or _resolve_company_id()
            
            # Convert amounts to float
            for field in ['gross_amount', 'tax_rate', 'tax_amount', 'net_amount']:
                if field in income_data:
                    income_data[field] = float(income_data[field])
            
            # Load existing data
            df = pd.read_parquet(self.income_file)
            
            # Add new record
            new_record = pd.DataFrame([income_data])
            df = pd.concat([df, new_record], ignore_index=True)
            
            # Save back to file
            df.to_parquet(self.income_file, index=False)
            return True
            
        except Exception as e:
            print(f"Error saving income record: {e}")
            return False
    
    def save_expense_record(self, expense_data: Dict[str, Any]) -> bool:
        """Save expense record to parquet file"""
        try:
            # Generate ID if not provided
            if 'id' not in expense_data:
                expense_data['id'] = f"EXP_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Add created timestamp
            expense_data['created_at'] = datetime.now().isoformat()
            
            # Inject company_id
            expense_data['company_id'] = expense_data.get('company_id') or _resolve_company_id()
            
            # Convert amounts to float
            for field in ['gross_amount', 'tax_rate', 'tax_amount', 'net_amount']:
                if field in expense_data:
                    expense_data[field] = float(expense_data[field])
            
            # Convert deductible to boolean
            if 'is_deductible' in expense_data:
                expense_data['is_deductible'] = str(expense_data['is_deductible']).lower() in ('true', '1', 'yes', 'on')
            
            # Load existing data
            df = pd.read_parquet(self.expense_file)
            
            # Add new record
            new_record = pd.DataFrame([expense_data])
            df = pd.concat([df, new_record], ignore_index=True)
            
            # Save back to file
            df.to_parquet(self.expense_file, index=False)
            return True
            
        except Exception as e:
            print(f"Error saving expense record: {e}")
            return False
    
    def get_all_income_records(self, company_id: str = None) -> List[Dict]:
        """Get all income records for the current company."""
        try:
            df = pd.read_parquet(self.income_file)
            if 'company_id' not in df.columns:
                df['company_id'] = 'default'
            cid = _resolve_company_id(company_id)
            df = df[df['company_id'] == cid]
            return df.to_dict('records')
        except Exception as e:
            print(f"Error loading income records: {e}")
            return []
    
    def get_all_expense_records(self, company_id: str = None) -> List[Dict]:
        """Get all expense records for the current company."""
        try:
            df = pd.read_parquet(self.expense_file)
            if 'company_id' not in df.columns:
                df['company_id'] = 'default'
            cid = _resolve_company_id(company_id)
            df = df[df['company_id'] == cid]
            return df.to_dict('records')
        except Exception as e:
            print(f"Error loading expense records: {e}")
            return []
    
    def get_income_record_by_id(self, record_id: str) -> Optional[Dict]:
        """Get specific income record by ID"""
        try:
            df = pd.read_parquet(self.income_file)
            record = df[df['id'] == record_id]
            if not record.empty:
                return record.iloc[0].to_dict()
            return None
        except Exception as e:
            print(f"Error loading income record: {e}")
            return None
    
    def get_expense_record_by_id(self, record_id: str) -> Optional[Dict]:
        """Get specific expense record by ID"""
        try:
            df = pd.read_parquet(self.expense_file)
            record = df[df['id'] == record_id]
            if not record.empty:
                return record.iloc[0].to_dict()
            return None
        except Exception as e:
            print(f"Error loading expense record: {e}")
            return None
    
    def delete_income_record(self, record_id: str) -> bool:
        """Delete income record by ID"""
        try:
            df = pd.read_parquet(self.income_file)
            df = df[df['id'] != record_id]
            df.to_parquet(self.income_file, index=False)
            return True
        except Exception as e:
            print(f"Error deleting income record: {e}")
            return False
    
    def delete_expense_record(self, record_id: str) -> bool:
        """Delete expense record by ID"""
        try:
            df = pd.read_parquet(self.expense_file)
            df = df[df['id'] != record_id]
            df.to_parquet(self.expense_file, index=False)
            return True
        except Exception as e:
            print(f"Error deleting expense record: {e}")
            return False
    
    def get_summary_statistics(self, date_from: Optional[str] = None, date_to: Optional[str] = None) -> Dict[str, Any]:
        """Get summary statistics for income and expenses, optionally filtered by date range.

        Args:
            date_from: inclusive start date string 'YYYY-MM-DD' (or None for no lower bound)
            date_to:   inclusive end date string   'YYYY-MM-DD' (or None for no upper bound)
        """
        try:
            income_df = pd.read_parquet(self.income_file)
            expense_df = pd.read_parquet(self.expense_file)

            # Company isolation
            cid = _resolve_company_id()
            for label, df_ref in [('income', income_df), ('expense', expense_df)]:
                if 'company_id' not in df_ref.columns:
                    df_ref['company_id'] = 'default'
            income_df = income_df[income_df.get('company_id', pd.Series('default', index=income_df.index)) == cid] if 'company_id' in income_df.columns else income_df
            expense_df = expense_df[expense_df.get('company_id', pd.Series('default', index=expense_df.index)) == cid] if 'company_id' in expense_df.columns else expense_df

            # Apply date filtering when bounds are given
            if date_from or date_to:
                for label, df in [('income', income_df), ('expense', expense_df)]:
                    if 'date' in df.columns and not df.empty:
                        dates = pd.to_datetime(df['date'], errors='coerce')
                        mask = pd.Series(True, index=df.index)
                        if date_from:
                            mask &= dates >= pd.Timestamp(date_from)
                        if date_to:
                            mask &= dates <= pd.Timestamp(date_to)
                        if label == 'income':
                            income_df = df[mask]
                        else:
                            expense_df = df[mask]

            total_income = income_df['net_amount'].sum() if not income_df.empty else 0
            total_expenses = expense_df['net_amount'].sum() if not expense_df.empty else 0
            
            return {
                'total_income': float(total_income),
                'total_expenses': float(total_expenses),
                'net_profit': float(total_income - total_expenses),
                'income_count': len(income_df),
                'expense_count': len(expense_df),
                'total_income_tax': float(income_df['tax_amount'].sum() if not income_df.empty else 0),
                'total_expense_tax': float(expense_df['tax_amount'].sum() if not expense_df.empty else 0)
            }
        except Exception as e:
            print(f"Error calculating statistics: {e}")
            return {
                'total_income': 0,
                'total_expenses': 0,
                'net_profit': 0,
                'income_count': 0,
                'expense_count': 0,
                'total_income_tax': 0,
                'total_expense_tax': 0
            }

    def get_date_range(self) -> Dict[str, Optional[str]]:
        """Return the earliest and latest record dates across income & expenses."""
        try:
            dates = []
            for fpath in (self.income_file, self.expense_file):
                df = pd.read_parquet(fpath)
                if not df.empty and 'date' in df.columns:
                    parsed = pd.to_datetime(df['date'], errors='coerce').dropna()
                    if not parsed.empty:
                        dates.append(parsed.min())
                        dates.append(parsed.max())
            if dates:
                return {
                    'min_date': min(dates).strftime('%Y-%m-%d'),
                    'max_date': max(dates).strftime('%Y-%m-%d'),
                }
        except Exception as e:
            print(f"Error getting date range: {e}")
        return {'min_date': None, 'max_date': None}
    
    def export_to_excel(self) -> str:
        """Export all data to Excel file"""
        try:
            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
            temp_file.close()
            
            # Load data
            income_df = pd.read_parquet(self.income_file)
            expense_df = pd.read_parquet(self.expense_file)
            
            # Create Excel writer
            with pd.ExcelWriter(temp_file.name, engine='openpyxl') as writer:
                # Write income records
                income_df.to_excel(writer, sheet_name='Income Records', index=False)
                
                # Write expense records
                expense_df.to_excel(writer, sheet_name='Expense Records', index=False)
                
                # Write summary
                summary = self.get_summary_statistics()
                summary_df = pd.DataFrame([summary])
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            return temp_file.name
            
        except Exception as e:
            print(f"Error exporting to Excel: {e}")
            return None
    
    def import_from_excel(self, file_path: str) -> Dict[str, Any]:
        """Import data from Excel file"""
        result = {
            'success': False,
            'message': '',
            'imported_income': 0,
            'imported_expenses': 0,
            'errors': []
        }
        
        try:
            # Read Excel file
            excel_sheets = pd.read_excel(file_path, sheet_name=None)
            
            # Import income records if sheet exists
            if 'Income Records' in excel_sheets:
                income_df = excel_sheets['Income Records']
                income_count = 0
                
                for _, row in income_df.iterrows():
                    try:
                        income_data = {
                            'date': str(row.get('date', datetime.now().date())),
                            'description': str(row.get('description', '')),
                            'category': str(row.get('category', 'General')),
                            'client_name': str(row.get('client_name', '')),
                            'client_tin': str(row.get('client_tin', '')),
                            'gross_amount': float(row.get('gross_amount', 0)),
                            'tax_rate': float(row.get('tax_rate', 0)),
                            'tax_amount': float(row.get('tax_amount', 0)),
                            'net_amount': float(row.get('net_amount', 0)),
                            'payment_method': str(row.get('payment_method', 'Cash')),
                            'reference_number': str(row.get('reference_number', ''))
                        }
                        
                        if self.save_income_record(income_data):
                            income_count += 1
                            
                    except Exception as e:
                        result['errors'].append(f"Income row error: {str(e)}")
                
                result['imported_income'] = income_count
            
            # Import expense records if sheet exists  
            if 'Expense Records' in excel_sheets:
                expense_df = excel_sheets['Expense Records']
                expense_count = 0
                
                for _, row in expense_df.iterrows():
                    try:
                        expense_data = {
                            'date': str(row.get('date', datetime.now().date())),
                            'description': str(row.get('description', '')),
                            'category': str(row.get('category', 'General')),
                            'supplier_name': str(row.get('supplier_name', '')),
                            'supplier_tin': str(row.get('supplier_tin', '')),
                            'gross_amount': float(row.get('gross_amount', 0)),
                            'tax_rate': float(row.get('tax_rate', 0)),
                            'tax_amount': float(row.get('tax_amount', 0)),
                            'net_amount': float(row.get('net_amount', 0)),
                            'payment_method': str(row.get('payment_method', 'Cash')),
                            'receipt_number': str(row.get('receipt_number', '')),
                            'is_deductible': bool(row.get('is_deductible', True))
                        }
                        
                        if self.save_expense_record(expense_data):
                            expense_count += 1
                            
                    except Exception as e:
                        result['errors'].append(f"Expense row error: {str(e)}")
                
                result['imported_expenses'] = expense_count
            
            result['success'] = True
            result['message'] = f"Successfully imported {result['imported_income']} income records and {result['imported_expenses']} expense records"
            
        except Exception as e:
            result['message'] = f"Import failed: {str(e)}"
            result['errors'].append(str(e))
        
        return result
    
    def create_sample_excel_file(self) -> str:
        """Create sample Excel file with Ethiopian business data"""
        try:
            # Sample income data
            sample_income = [
                {
                    'id': 'INC_20260219_001',
                    'date': '2026-02-15',
                    'description': 'Coffee Export Sales - Premium Grade',
                    'category': 'Product Sales',
                    'client_name': 'International Coffee Buyers LLC',
                    'client_tin': 'TIN_CLIENT_001',
                    'gross_amount': 125000.00,
                    'tax_rate': 0.15,
                    'tax_amount': 18750.00,
                    'net_amount': 106250.00,
                    'payment_method': 'Bank Transfer',
                    'reference_number': 'INV-2026-001',
                    'created_at': '2026-02-19T10:00:00'
                },
                {
                    'id': 'INC_20260219_002',
                    'date': '2026-02-10',
                    'description': 'Software Development Services',
                    'category': 'Services',
                    'client_name': 'Addis Ababa Municipality',
                    'client_tin': 'TIN_CLIENT_002',
                    'gross_amount': 85000.00,
                    'tax_rate': 0.15,
                    'tax_amount': 12750.00,
                    'net_amount': 72250.00,
                    'payment_method': 'Government Payment',
                    'reference_number': 'SERV-2026-002',
                    'created_at': '2026-02-19T09:00:00'
                },
                {
                    'id': 'INC_20260219_003',
                    'date': '2026-02-05',
                    'description': 'Consulting Services - Business Strategy',
                    'category': 'Consulting',
                    'client_name': 'Ethiopian Airlines',
                    'client_tin': 'TIN_CLIENT_003',
                    'gross_amount': 55000.00,
                    'tax_rate': 0.15,
                    'tax_amount': 8250.00,
                    'net_amount': 46750.00,
                    'payment_method': 'Bank Transfer',
                    'reference_number': 'CON-2026-003',
                    'created_at': '2026-02-19T08:00:00'
                }
            ]
            
            # Sample expense data
            sample_expenses = [
                {
                    'id': 'EXP_20260219_001',
                    'date': '2026-02-18',
                    'description': 'Office Rent - Monthly Payment',
                    'category': 'Office Expenses',
                    'supplier_name': 'Bole Real Estate Company',
                    'supplier_tin': 'TIN_SUPPLIER_001',
                    'gross_amount': 25000.00,
                    'tax_rate': 0.15,
                    'tax_amount': 3750.00,
                    'net_amount': 21250.00,
                    'payment_method': 'Bank Transfer',
                    'receipt_number': 'RENT-2026-002',
                    'is_deductible': True,
                    'created_at': '2026-02-19T14:00:00'
                },
                {
                    'id': 'EXP_20260219_002',
                    'date': '2026-02-12',
                    'description': 'Computer Equipment Purchase',
                    'category': 'Equipment',
                    'supplier_name': 'Tekleberhan IT Solutions',
                    'supplier_tin': 'TIN_SUPPLIER_002',
                    'gross_amount': 45000.00,
                    'tax_rate': 0.15,
                    'tax_amount': 6750.00,
                    'net_amount': 38250.00,
                    'payment_method': 'Cash',
                    'receipt_number': 'EQP-2026-001',
                    'is_deductible': True,
                    'created_at': '2026-02-19T13:00:00'
                },
                {
                    'id': 'EXP_20260219_003',
                    'date': '2026-02-08',
                    'description': 'Utility Bills - Electricity and Water',
                    'category': 'Utilities',
                    'supplier_name': 'Ethiopian Electric Utility',
                    'supplier_tin': 'TIN_SUPPLIER_003',
                    'gross_amount': 8500.00,
                    'tax_rate': 0.15,
                    'tax_amount': 1275.00,
                    'net_amount': 7225.00,
                    'payment_method': 'Bank Transfer',
                    'receipt_number': 'UTIL-2026-001',
                    'is_deductible': True,
                    'created_at': '2026-02-19T12:00:00'
                },
                {
                    'id': 'EXP_20260219_004',
                    'date': '2026-02-03',
                    'description': 'Marketing and Advertising Campaign',
                    'category': 'Marketing',
                    'supplier_name': 'Sheger Media Group',
                    'supplier_tin': 'TIN_SUPPLIER_004',
                    'gross_amount': 15000.00,
                    'tax_rate': 0.15,
                    'tax_amount': 2250.00,
                    'net_amount': 12750.00,
                    'payment_method': 'Bank Transfer',
                    'receipt_number': 'MKT-2026-001',
                    'is_deductible': True,
                    'created_at': '2026-02-19T11:00:00'
                }
            ]
            
            # Create DataFrames
            income_df = pd.DataFrame(sample_income)
            expense_df = pd.DataFrame(sample_expenses)
            
            # Create sample file path
            sample_file = os.path.join(self.data_dir, 'income_expense_sample_data.xlsx')
            
            # Create Excel file
            with pd.ExcelWriter(sample_file, engine='openpyxl') as writer:
                # Write income records
                income_df.to_excel(writer, sheet_name='Income Records', index=False)
                
                # Write expense records  
                expense_df.to_excel(writer, sheet_name='Expense Records', index=False)
                
                # Create summary
                total_income = income_df['net_amount'].sum()
                total_expenses = expense_df['net_amount'].sum()
                
                summary_data = {
                    'Metric': ['Total Income', 'Total Expenses', 'Net Profit', 'Total Income Tax', 'Total Expense Tax'],
                    'Amount (ETB)': [
                        total_income,
                        total_expenses,
                        total_income - total_expenses,
                        income_df['tax_amount'].sum(),
                        expense_df['tax_amount'].sum()
                    ]
                }
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            return sample_file
            
        except Exception as e:
            print(f"Error creating sample file: {e}")
            return None

__all__ = ['IncomeExpenseDataStore']