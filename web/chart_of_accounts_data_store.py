"""
Chart of Accounts Data Store - Parquet-based persistence for Chart of Accounts

Handles data persistence for chart of accounts using Parquet files.
"""

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from datetime import datetime, date
from typing import Dict, List, Any, Optional
import uuid
import os


# Data directory for accounts files
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Parquet file paths
ACCOUNTS_PARQUET_FILE = DATA_DIR / 'chart_of_accounts.parquet'


class ChartOfAccountsDataStore:
    """Parquet-based data storage for chart of accounts"""
    
    def __init__(self):
        self.schema = self._define_schema()
        self._initialize_data_file()
    
    def _define_schema(self) -> pa.Schema:
        """Define PyArrow schema for accounts data"""
        return pa.schema([
            ('account_code', pa.string()),
            ('account_name', pa.string()),
            ('account_type', pa.string()),
            ('account_subtype', pa.string()),
            ('parent_account', pa.string()),
            ('description', pa.string()),
            ('is_active', pa.bool_()),
            ('normal_balance', pa.string()),  # 'Debit' or 'Credit'
            ('current_balance', pa.float64()),
            ('created_date', pa.string()),  # Store as string initially
            ('modified_date', pa.string()),  # Store as string initially
            ('company_id', pa.string())
        ])
    
    def _initialize_data_file(self):
        """Initialize parquet file with schema if it doesn't exist"""
        if not ACCOUNTS_PARQUET_FILE.exists():
            # Create empty dataframe with correct columns
            empty_data = {field.name: [] for field in self.schema}
            empty_df = pd.DataFrame(empty_data)
            
            # Convert to table with schema
            empty_table = pa.Table.from_pandas(empty_df, schema=self.schema)
            pq.write_table(empty_table, ACCOUNTS_PARQUET_FILE)
            
            # Load default chart of accounts
            self._load_default_accounts()
    
    def _load_default_accounts(self):
        """Load default Ethiopian chart of accounts"""
        default_accounts = [
            # Assets
            {'account_code': '1000', 'account_name': 'Cash', 'account_type': 'Asset', 'account_subtype': 'Current Asset', 'normal_balance': 'Debit'},
            {'account_code': '1100', 'account_name': 'Petty Cash', 'account_type': 'Asset', 'account_subtype': 'Current Asset', 'normal_balance': 'Debit'},
            {'account_code': '1200', 'account_name': 'Accounts Receivable', 'account_type': 'Asset', 'account_subtype': 'Current Asset', 'normal_balance': 'Debit'},
            {'account_code': '1300', 'account_name': 'Inventory', 'account_type': 'Asset', 'account_subtype': 'Current Asset', 'normal_balance': 'Debit'},
            {'account_code': '1400', 'account_name': 'Prepaid Expenses', 'account_type': 'Asset', 'account_subtype': 'Current Asset', 'normal_balance': 'Debit'},
            {'account_code': '1500', 'account_name': 'Office Equipment', 'account_type': 'Asset', 'account_subtype': 'Fixed Asset', 'normal_balance': 'Debit'},
            {'account_code': '1600', 'account_name': 'Furniture & Fixtures', 'account_type': 'Asset', 'account_subtype': 'Fixed Asset', 'normal_balance': 'Debit'},
            {'account_code': '1700', 'account_name': 'Vehicles', 'account_type': 'Asset', 'account_subtype': 'Fixed Asset', 'normal_balance': 'Debit'},
            {'account_code': '1800', 'account_name': 'Buildings', 'account_type': 'Asset', 'account_subtype': 'Fixed Asset', 'normal_balance': 'Debit'},
            {'account_code': '1900', 'account_name': 'Land', 'account_type': 'Asset', 'account_subtype': 'Fixed Asset', 'normal_balance': 'Debit'},
            
            # Liabilities
            {'account_code': '2000', 'account_name': 'Accounts Payable', 'account_type': 'Liability', 'account_subtype': 'Current Liability', 'normal_balance': 'Credit'},
            {'account_code': '2100', 'account_name': 'Accrued Expenses', 'account_type': 'Liability', 'account_subtype': 'Current Liability', 'normal_balance': 'Credit'},
            {'account_code': '2200', 'account_name': 'Salaries Payable', 'account_type': 'Liability', 'account_subtype': 'Current Liability', 'normal_balance': 'Credit'},
            {'account_code': '2300', 'account_name': 'Income Tax Payable', 'account_type': 'Liability', 'account_subtype': 'Current Liability', 'normal_balance': 'Credit'},
            {'account_code': '2400', 'account_name': 'VAT Payable', 'account_type': 'Liability', 'account_subtype': 'Current Liability', 'normal_balance': 'Credit'},
            {'account_code': '2500', 'account_name': 'Short-term Loans', 'account_type': 'Liability', 'account_subtype': 'Current Liability', 'normal_balance': 'Credit'},
            {'account_code': '2600', 'account_name': 'Long-term Debt', 'account_type': 'Liability', 'account_subtype': 'Long-term Liability', 'normal_balance': 'Credit'},
            
            # Equity
            {'account_code': '3000', 'account_name': 'Owner Capital', 'account_type': 'Equity', 'account_subtype': 'Capital', 'normal_balance': 'Credit'},
            {'account_code': '3100', 'account_name': 'Retained Earnings', 'account_type': 'Equity', 'account_subtype': 'Retained Earnings', 'normal_balance': 'Credit'},
            {'account_code': '3200', 'account_name': 'Owner Drawings', 'account_type': 'Equity', 'account_subtype': 'Drawings', 'normal_balance': 'Debit'},
            
            # Revenue
            {'account_code': '4000', 'account_name': 'Service Revenue', 'account_type': 'Revenue', 'account_subtype': 'Operating Revenue', 'normal_balance': 'Credit'},
            {'account_code': '4100', 'account_name': 'Sales Revenue', 'account_type': 'Revenue', 'account_subtype': 'Operating Revenue', 'normal_balance': 'Credit'},
            {'account_code': '4200', 'account_name': 'Interest Income', 'account_type': 'Revenue', 'account_subtype': 'Other Income', 'normal_balance': 'Credit'},
            {'account_code': '4300', 'account_name': 'Other Income', 'account_type': 'Revenue', 'account_subtype': 'Other Income', 'normal_balance': 'Credit'},
            
            # Expenses
            {'account_code': '5000', 'account_name': 'Cost of Goods Sold', 'account_type': 'Expense', 'account_subtype': 'Cost of Sales', 'normal_balance': 'Debit'},
            {'account_code': '6000', 'account_name': 'Salary Expense', 'account_type': 'Expense', 'account_subtype': 'Operating Expense', 'normal_balance': 'Debit'},
            {'account_code': '6100', 'account_name': 'Rent Expense', 'account_type': 'Expense', 'account_subtype': 'Operating Expense', 'normal_balance': 'Debit'},
            {'account_code': '6200', 'account_name': 'Utilities Expense', 'account_type': 'Expense', 'account_subtype': 'Operating Expense', 'normal_balance': 'Debit'},
            {'account_code': '6300', 'account_name': 'Office Supplies Expense', 'account_type': 'Expense', 'account_subtype': 'Operating Expense', 'normal_balance': 'Debit'},
            {'account_code': '6400', 'account_name': 'Advertising Expense', 'account_type': 'Expense', 'account_subtype': 'Operating Expense', 'normal_balance': 'Debit'},
            {'account_code': '6500', 'account_name': 'Professional Services', 'account_type': 'Expense', 'account_subtype': 'Operating Expense', 'normal_balance': 'Debit'},
            {'account_code': '6600', 'account_name': 'Insurance Expense', 'account_type': 'Expense', 'account_subtype': 'Operating Expense', 'normal_balance': 'Debit'},
            {'account_code': '6700', 'account_name': 'Depreciation Expense', 'account_type': 'Expense', 'account_subtype': 'Operating Expense', 'normal_balance': 'Debit'},
            {'account_code': '6800', 'account_name': 'Interest Expense', 'account_type': 'Expense', 'account_subtype': 'Financial Expense', 'normal_balance': 'Debit'},
            {'account_code': '6900', 'account_name': 'Miscellaneous Expense', 'account_type': 'Expense', 'account_subtype': 'Operating Expense', 'normal_balance': 'Debit'},
        ]
        
        # Add metadata to default accounts
        current_date = str(date.today())
        for account in default_accounts:
            account.update({
                'parent_account': '',
                'description': f'Default {account["account_name"]} account',
                'is_active': True,
                'current_balance': 0.0,
                'created_date': current_date,
                'modified_date': current_date,
                'company_id': 'default'
            })
        
        accounts_df = pd.DataFrame(default_accounts)
        self._save_accounts(accounts_df)
    
    def read_all_accounts(self, company_id: str = None) -> pd.DataFrame:
        """Read all accounts with optional company filter"""
        try:
            filters = [('is_active', '==', True)]
            if company_id:
                filters.append(('company_id', '==', company_id))
            
            table = pq.read_table(ACCOUNTS_PARQUET_FILE, filters=filters)
            return table.to_pandas()
        except:
            return pd.DataFrame()
    
    def get_account_by_code(self, account_code: str, company_id: str = None) -> Optional[Dict[str, Any]]:
        """Get account by account code"""
        filters = [('account_code', '==', account_code), ('is_active', '==', True)]
        if company_id:
            filters.append(('company_id', '==', company_id))
        
        try:
            table = pq.read_table(ACCOUNTS_PARQUET_FILE, filters=filters)
            df = table.to_pandas()
            
            if not df.empty:
                return df.iloc[0].to_dict()
            return None
        except:
            return None
    
    def save_account(self, account_data: Dict[str, Any]) -> bool:
        """Save or update an account"""
        try:
            # Prepare account data
            account = {
                'account_code': account_data['account_code'],
                'account_name': account_data['account_name'],
                'account_type': account_data['account_type'],
                'account_subtype': account_data.get('account_subtype', ''),
                'parent_account': account_data.get('parent_account', ''),
                'description': account_data.get('description', ''),
                'is_active': account_data.get('is_active', True),
                'normal_balance': account_data.get('normal_balance', 'Debit'),
                'current_balance': float(account_data.get('current_balance', 0)),
                'created_date': str(account_data.get('created_date', date.today())),
                'modified_date': str(date.today()),
                'company_id': account_data.get('company_id', 'default')
            }
            
            # Check if account exists
            existing = self.get_account_by_code(account['account_code'], account['company_id'])
            
            if existing:
                # Update existing account
                self._update_account(account)
            else:
                # Add new account
                new_account_df = pd.DataFrame([account])
                self._append_accounts(new_account_df)
            
            return True
        
        except Exception as e:
            print(f"Error saving account: {e}")
            return False
    
    def _save_accounts(self, accounts_df: pd.DataFrame):
        """Save accounts to parquet file"""
        table = pa.Table.from_pandas(accounts_df, schema=self.schema)
        pq.write_table(table, ACCOUNTS_PARQUET_FILE)
    
    def _append_accounts(self, new_accounts_df: pd.DataFrame):
        """Append accounts to existing file"""
        try:
            existing_df = self.read_all_accounts()
            updated_df = pd.concat([existing_df, new_accounts_df], ignore_index=True)
        except:
            updated_df = new_accounts_df
        
        self._save_accounts(updated_df)
    
    def _update_account(self, account_data: Dict[str, Any]):
        """Update existing account"""
        all_accounts = self.read_all_accounts()
        
        # Update the specific account
        mask = (all_accounts['account_code'] == account_data['account_code']) & \
               (all_accounts['company_id'] == account_data['company_id'])
        
        for field, value in account_data.items():
            if field in all_accounts.columns:
                all_accounts.loc[mask, field] = value
        
        self._save_accounts(all_accounts)
    
    def bulk_import_accounts(self, accounts_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Bulk import accounts from Excel data"""
        result = {'success': False, 'imported_count': 0, 'errors': []}
        
        try:
            valid_accounts = []
            
            for i, account in enumerate(accounts_data):
                try:
                    if self._validate_account(account):
                        # Ensure required fields
                        account['is_active'] = account.get('is_active', True)
                        account['current_balance'] = float(account.get('current_balance', 0))
                        account['created_date'] = account.get('created_date', date.today())
                        account['modified_date'] = date.today()
                        account['company_id'] = account.get('company_id', 'default')
                        
                        valid_accounts.append(account)
                    else:
                        result['errors'].append(f'Invalid account data at row {i+1}')
                        
                except Exception as e:
                    result['errors'].append(f'Error processing account {i+1}: {str(e)}')
            
            # Import valid accounts
            if valid_accounts:
                for account in valid_accounts:
                    if self.save_account(account):
                        result['imported_count'] += 1
                    else:
                        result['errors'].append(f'Failed to save account: {account.get("account_code", "unknown")}')
            
            result['success'] = True
            
        except Exception as e:
            result['errors'].append(f'Bulk import error: {str(e)}')
        
        return result
    
    def _validate_account(self, account: Dict[str, Any]) -> bool:
        """Validate account data"""
        required_fields = ['account_code', 'account_name', 'account_type']
        
        for field in required_fields:
            if field not in account or not account[field]:
                return False
        
        # Validate account type
        valid_types = ['Asset', 'Liability', 'Equity', 'Revenue', 'Expense']
        if account['account_type'] not in valid_types:
            return False
        
        return True
    
    def export_to_excel(self, company_id: str = None, filename: str = None) -> str:
        """Export chart of accounts to Excel"""
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            company_str = f'_{company_id}' if company_id else ''
            filename = f'chart_of_accounts{company_str}_{timestamp}.xlsx'
        
        filepath = DATA_DIR / filename
        
        accounts_df = self.read_all_accounts(company_id)
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            if not accounts_df.empty:
                # Clean data for export
                export_df = accounts_df.copy()
                export_df = export_df.drop(['company_id'], axis=1, errors='ignore')
                export_df.to_excel(writer, sheet_name='Chart of Accounts', index=False)
            
            # Create template for import
            template_data = pd.DataFrame([
                {
                    'account_code': '7000',
                    'account_name': 'New Account',
                    'account_type': 'Expense',
                    'account_subtype': 'Operating Expense',
                    'parent_account': '',
                    'description': 'Sample account for import',
                    'normal_balance': 'Debit',
                    'current_balance': 0.0
                }
            ])
            template_data.to_excel(writer, sheet_name='Import Template', index=False)
        
        return str(filepath)
    
    def import_from_excel(self, excel_file: str, company_id: str = 'default') -> Dict[str, Any]:
        """Import chart of accounts from Excel file"""
        result = {'success': False, 'imported_count': 0, 'errors': []}
        
        try:
            # Read from Import Template sheet
            df = pd.read_excel(excel_file, sheet_name='Import Template')
            
            accounts_to_import = []
            
            for _, row in df.iterrows():
                account = row.to_dict()
                account['company_id'] = company_id
                accounts_to_import.append(account)
            
            # Import accounts
            import_result = self.bulk_import_accounts(accounts_to_import)
            result.update(import_result)
            
        except Exception as e:
            result['errors'].append(f'Excel import error: {str(e)}')
        
        return result
    
    def create_sample_excel_file(self, filename: str = None) -> str:
        """Create sample Excel file for chart of accounts"""
        if filename is None:
            filename = 'chart_of_accounts_sample_data.xlsx'
        
        filepath = DATA_DIR / filename
        
        sample_accounts = pd.DataFrame([
            {
                'account_code': '7000',
                'account_name': 'Travel Expense',
                'account_type': 'Expense',
                'account_subtype': 'Operating Expense',
                'parent_account': '',
                'description': 'Business travel and transportation costs',
                'normal_balance': 'Debit',
                'current_balance': 0.0
            },
            {
                'account_code': '7100',
                'account_name': 'Training Expense',
                'account_type': 'Expense',
                'account_subtype': 'Operating Expense',
                'parent_account': '',
                'description': 'Employee training and development costs',
                'normal_balance': 'Debit',
                'current_balance': 0.0
            },
            {
                'account_code': '1050',
                'account_name': 'Bank Account - CBE',
                'account_type': 'Asset',
                'account_subtype': 'Current Asset',
                'parent_account': '1000',
                'description': 'Commercial Bank of Ethiopia checking account',
                'normal_balance': 'Debit',
                'current_balance': 0.0
            },
            {
                'account_code': '4150',
                'account_name': 'Consulting Revenue',
                'account_type': 'Revenue',
                'account_subtype': 'Operating Revenue',
                'parent_account': '4000',
                'description': 'Revenue from consulting services',
                'normal_balance': 'Credit',
                'current_balance': 0.0
            }
        ])
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            sample_accounts.to_excel(writer, sheet_name='Import Template', index=False)
            
            # Instructions
            instructions = pd.DataFrame([
                {'Field': 'account_code', 'Description': 'Unique account code (e.g., 1000)', 'Required': 'Yes'},
                {'Field': 'account_name', 'Description': 'Account name', 'Required': 'Yes'},
                {'Field': 'account_type', 'Description': 'Asset, Liability, Equity, Revenue, Expense', 'Required': 'Yes'},
                {'Field': 'account_subtype', 'Description': 'Sub-classification of account type', 'Required': 'No'},
                {'Field': 'parent_account', 'Description': 'Parent account code for sub-accounts', 'Required': 'No'},
                {'Field': 'description', 'Description': 'Account description', 'Required': 'No'},
                {'Field': 'normal_balance', 'Description': 'Debit or Credit (based on account type)', 'Required': 'No'},
                {'Field': 'current_balance', 'Description': 'Starting balance (default 0)', 'Required': 'No'}
            ])
            instructions.to_excel(writer, sheet_name='Instructions', index=False)
        
        return str(filepath)

__all__ = ['ChartOfAccountsDataStore']