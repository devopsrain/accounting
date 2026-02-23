"""
VAT Data Store - Parquet-based persistence for VAT Portal

Handles data persistence for VAT income, expenses, and capital records using Parquet files.
"""

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from datetime import datetime, date
from typing import Dict, List, Any, Optional
import uuid
import os

# Data directory for VAT files
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Parquet file paths
VAT_PARQUET_FILES = {
    'vat_income': DATA_DIR / 'vat_income.parquet',
    'vat_expenses': DATA_DIR / 'vat_expenses.parquet',
    'vat_capital': DATA_DIR / 'vat_capital.parquet',
}

class VATDataStore:
    """Parquet-based data storage for VAT records"""
    
    def __init__(self):
        self.schemas = self._define_schemas()
        self._initialize_data_files()
    
    def _define_schemas(self) -> Dict[str, pa.Schema]:
        """Define PyArrow schemas for VAT data entities"""
        return {
            'vat_income': pa.schema([
                ('income_id', pa.string()),
                ('company_id', pa.string()),
                ('contract_date', pa.date32()),
                ('description', pa.string()),
                ('category', pa.string()),
                ('gross_amount', pa.float64()),
                ('vat_type', pa.string()),
                ('vat_rate', pa.float64()),
                ('vat_amount', pa.float64()),
                ('net_amount', pa.float64()),
                ('customer_name', pa.string()),
                ('customer_tin', pa.string()),
                ('invoice_number', pa.string()),
                ('created_date', pa.timestamp('ns')),
                ('updated_date', pa.timestamp('ns')),
                ('created_by', pa.string()),
                ('is_active', pa.bool_())
            ]),
            
            'vat_expenses': pa.schema([
                ('expense_id', pa.string()),
                ('company_id', pa.string()),
                ('expense_date', pa.date32()),
                ('description', pa.string()),
                ('category', pa.string()),
                ('gross_amount', pa.float64()),
                ('vat_type', pa.string()),
                ('vat_rate', pa.float64()),
                ('vat_amount', pa.float64()),
                ('net_amount', pa.float64()),
                ('supplier_name', pa.string()),
                ('supplier_tin', pa.string()),
                ('receipt_number', pa.string()),
                ('created_date', pa.timestamp('ns')),
                ('updated_date', pa.timestamp('ns')),
                ('created_by', pa.string()),
                ('is_active', pa.bool_())
            ]),
            
            'vat_capital': pa.schema([
                ('capital_id', pa.string()),
                ('company_id', pa.string()),
                ('investment_date', pa.date32()),
                ('description', pa.string()),
                ('capital_type', pa.string()),
                ('amount', pa.float64()),
                ('vat_type', pa.string()),
                ('vat_rate', pa.float64()),
                ('vat_amount', pa.float64()),
                ('investor_name', pa.string()),
                ('investor_tin', pa.string()),
                ('created_date', pa.timestamp('ns')),
                ('updated_date', pa.timestamp('ns')),
                ('created_by', pa.string()),
                ('is_active', pa.bool_())
            ])
        }
    
    def _initialize_data_files(self):
        """Create empty Parquet files if they don't exist"""
        for table_name, file_path in VAT_PARQUET_FILES.items():
            if not file_path.exists():
                try:
                    schema = self.schemas[table_name]
                    # Create empty DataFrame with schema
                    empty_df = pd.DataFrame({field.name: pd.Series(dtype=self._pa_to_pandas_dtype(field.type)) 
                                           for field in schema})
                    
                    # Ensure proper data types
                    empty_df = self._ensure_dtypes(empty_df, table_name)
                    
                    # Write to parquet
                    empty_df.to_parquet(file_path, index=False)
                    print(f"Created {table_name}.parquet")
                except Exception as e:
                    print(f"Warning: Could not create {table_name}.parquet: {e}")
    
    def _pa_to_pandas_dtype(self, pa_type):
        """Convert PyArrow type to pandas dtype"""
        if pa.types.is_string(pa_type):
            return 'object'
        elif pa.types.is_float64(pa_type):
            return 'float64'
        elif pa.types.is_date32(pa_type):
            return 'datetime64[ns]'
        elif pa.types.is_timestamp(pa_type):
            return 'datetime64[ns]'
        elif pa.types.is_boolean(pa_type):
            return 'bool'
        else:
            return 'object'
    
    def _ensure_dtypes(self, df: pd.DataFrame, table_name: str) -> pd.DataFrame:
        """Ensure DataFrame has correct data types"""
        if table_name in ['vat_income', 'vat_expenses']:
            date_col = 'contract_date' if table_name == 'vat_income' else 'expense_date'
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(df[date_col]).dt.date
        elif table_name == 'vat_capital':
            if 'investment_date' in df.columns:
                df['investment_date'] = pd.to_datetime(df['investment_date']).dt.date
        
        # Ensure timestamp columns
        for col in ['created_date', 'updated_date']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
        
        # Ensure boolean columns
        if 'is_active' in df.columns:
            df['is_active'] = df['is_active'].astype(bool)
        
        return df
    
    def read_data(self, table_name: str, filters: Optional[List] = None, 
                  columns: Optional[List[str]] = None) -> pd.DataFrame:
        """Read data from Parquet table with optional filtering"""
        file_path = VAT_PARQUET_FILES.get(table_name)
        if not file_path or not file_path.exists():
            return pd.DataFrame()
        
        try:
            df = pd.read_parquet(file_path, filters=filters, columns=columns)
            return self._ensure_dtypes(df, table_name)
        except Exception as e:
            print(f"Error reading {table_name}: {e}")
            return pd.DataFrame()
    
    def write_data(self, table_name: str, df: pd.DataFrame, append: bool = True):
        """Write DataFrame to Parquet table"""
        file_path = VAT_PARQUET_FILES.get(table_name)
        if not file_path:
            raise ValueError(f"Unknown table: {table_name}")
        
        try:
            # Ensure correct data types
            df = self._ensure_dtypes(df, table_name)
            
            if append and file_path.exists():
                # Read existing data and append
                existing_df = self.read_data(table_name)
                if not existing_df.empty:
                    df = pd.concat([existing_df, df], ignore_index=True)
            
            # Write to parquet
            df.to_parquet(file_path, index=False)
            
        except Exception as e:
            print(f"Error writing to {table_name}: {e}")
            raise
    
    def add_record(self, table_name: str, record_data: dict):
        """Add a single record to the table"""
        # Convert to DataFrame
        df = pd.DataFrame([record_data])
        
        # Add timestamps
        now = datetime.now()
        if 'created_date' not in record_data:
            df['created_date'] = now
        if 'updated_date' not in record_data:
            df['updated_date'] = now
        if 'is_active' not in record_data:
            df['is_active'] = True
        
        # Write data
        self.write_data(table_name, df, append=True)
    
    def get_company_records(self, table_name: str, company_id: str, 
                           start_date: Optional[date] = None, 
                           end_date: Optional[date] = None) -> pd.DataFrame:
        """Get records for a company within optional date range"""
        filters = [('company_id', '==', company_id), ('is_active', '==', True)]
        
        # Add date filters if provided
        if start_date or end_date:
            date_col = self._get_date_column(table_name)
            if start_date:
                filters.append((date_col, '>=', start_date))
            if end_date:
                filters.append((date_col, '<=', end_date))
        
        return self.read_data(table_name, filters=filters)
    
    def _get_date_column(self, table_name: str) -> str:
        """Get the main date column for a table"""
        date_columns = {
            'vat_income': 'contract_date',
            'vat_expenses': 'expense_date',
            'vat_capital': 'investment_date'
        }
        return date_columns.get(table_name, 'created_date')
    
    def get_statistics(self, company_id: str) -> Dict[str, Any]:
        """Get summary statistics for a company"""
        stats = {}
        
        for table_name in VAT_PARQUET_FILES.keys():
            df = self.get_company_records(table_name, company_id)
            
            if not df.empty:
                amount_col = 'gross_amount' if table_name != 'vat_capital' else 'amount'
                stats[f"{table_name}_count"] = len(df)
                stats[f"{table_name}_total"] = df[amount_col].sum() if amount_col in df.columns else 0
                
                # VAT amounts
                if 'vat_amount' in df.columns:
                    stats[f"{table_name}_vat_total"] = df['vat_amount'].sum()
            else:
                stats[f"{table_name}_count"] = 0
                stats[f"{table_name}_total"] = 0
                stats[f"{table_name}_vat_total"] = 0
        
        return stats
    
    # Excel Import/Export functionality
    def export_to_excel(self, company_id: str, filename: str = None) -> str:
        """Export VAT data to Excel file"""
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'vat_export_{company_id}_{timestamp}.xlsx'
        
        filepath = DATA_DIR / filename
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            # Export each VAT table
            for table_name, _ in VAT_PARQUET_FILES.items():
                df = self.get_company_records(table_name, company_id)
                if not df.empty:
                    # Clean column names for Excel
                    df_export = df.copy()
                    df_export = df_export.drop(['company_id', 'is_active'], axis=1, errors='ignore')
                    
                    # Format dates for Excel
                    date_cols = df_export.select_dtypes(include=['datetime64', 'object']).columns
                    for col in date_cols:
                        if 'date' in col.lower():
                            df_export[col] = pd.to_datetime(df_export[col], errors='ignore')
                    
                    sheet_name = table_name.replace('vat_', '').title()
                    df_export.to_excel(writer, sheet_name=sheet_name, index=False)
        
        return str(filepath)
    
    def import_from_excel(self, company_id: str, excel_file: str) -> Dict[str, Any]:
        """Import VAT data from Excel file"""
        result = {'success': False, 'imported_counts': {}, 'errors': []}
        
        try:
            # Read all sheets
            excel_data = pd.read_excel(excel_file, sheet_name=None)
            
            for sheet_name, df in excel_data.items():
                if df.empty:
                    continue
                
                # Map sheet names to table names
                table_mapping = {
                    'Income': 'vat_income',
                    'Expenses': 'vat_expenses', 
                    'Capital': 'vat_capital'
                }
                
                table_name = table_mapping.get(sheet_name)
                if not table_name:
                    result['errors'].append(f'Unknown sheet: {sheet_name}')
                    continue
                
                # Validate and prepare data
                valid_records = []
                for idx, row in df.iterrows():
                    try:
                        # Add common fields
                        record = row.to_dict()
                        record['company_id'] = company_id
                        record['is_active'] = True
                        record['created_date'] = datetime.now().date()
                        
                        # Generate ID if not present
                        id_field = f"{table_name.split('_')[1]}_id"
                        if id_field not in record or pd.isna(record[id_field]):
                            record[id_field] = str(uuid.uuid4())
                        
                        # Validate required fields
                        if self._validate_vat_record(table_name, record):
                            valid_records.append(record)
                        else:
                            result['errors'].append(f'Invalid record at row {idx+1} in {sheet_name}')
                            
                    except Exception as e:
                        result['errors'].append(f'Error processing row {idx+1} in {sheet_name}: {str(e)}')
                
                # Bulk import valid records
                if valid_records:
                    records_df = pd.DataFrame(valid_records)
                    self.write_data(table_name, records_df, append=True)
                    result['imported_counts'][sheet_name] = len(valid_records)
            
            result['success'] = True
            
        except Exception as e:
            result['errors'].append(f'Excel import error: {str(e)}')
        
        return result
    
    def _validate_vat_record(self, table_name: str, record: Dict[str, Any]) -> bool:
        """Validate VAT record based on table type"""
        try:
            if table_name == 'vat_income':
                return (record.get('description') and 
                        record.get('gross_amount', 0) > 0 and
                        record.get('contract_date'))
            elif table_name == 'vat_expenses':
                return (record.get('description') and 
                        record.get('gross_amount', 0) > 0 and
                        record.get('expense_date'))
            elif table_name == 'vat_capital':
                return (record.get('description') and 
                        record.get('amount', 0) > 0 and
                        record.get('investment_date'))
            return False
        except:
            return False
    
    def create_sample_excel_file(self, filename: str = None) -> str:
        """Create sample Excel file with templates for VAT data"""
        if filename is None:
            filename = 'vat_sample_data.xlsx'
        
        filepath = DATA_DIR / filename
        
        # Sample data
        sample_income = pd.DataFrame([
            {
                'description': 'Software Development Service',
                'category': 'Service Income',
                'contract_date': '2026-01-15',
                'gross_amount': 50000,
                'vat_type': 'Standard',
                'vat_rate': 15.0,
                'vat_amount': 7500,
                'net_amount': 42500,
                'customer_name': 'Tech Corp Ltd',
                'customer_tin': 'TIN123456789',
                'invoice_number': 'INV-2026-001'
            },
            {
                'description': 'Consulting Services',
                'category': 'Professional Services',
                'contract_date': '2026-01-20',
                'gross_amount': 25000,
                'vat_type': 'Standard',
                'vat_rate': 15.0,
                'vat_amount': 3750,
                'net_amount': 21250,
                'customer_name': 'Business Solutions Inc',
                'customer_tin': 'TIN987654321',
                'invoice_number': 'INV-2026-002'
            }
        ])
        
        sample_expenses = pd.DataFrame([
            {
                'description': 'Office Rent',
                'category': 'Rent Expense',
                'expense_date': '2026-01-01',
                'gross_amount': 15000,
                'vat_type': 'Standard',
                'vat_rate': 15.0,
                'vat_amount': 2250,
                'net_amount': 12750,
                'supplier_name': 'Property Management Co',
                'supplier_tin': 'TIN456789123',
                'receipt_number': 'REC-2026-001',
                'is_vat_applicable': True
            },
            {
                'description': 'Office Supplies',
                'category': 'Office Expenses',
                'expense_date': '2026-01-05',
                'gross_amount': 5000,
                'vat_type': 'Standard',  
                'vat_rate': 15.0,
                'vat_amount': 750,
                'net_amount': 4250,
                'supplier_name': 'Stationery Plus',
                'supplier_tin': 'TIN789123456',
                'receipt_number': 'REC-2026-002',
                'is_vat_applicable': True
            }
        ])
        
        sample_capital = pd.DataFrame([
            {
                'description': 'Computer Equipment',
                'capital_type': 'Equipment',
                'investment_date': '2026-01-10',
                'amount': 80000,
                'source': 'Owner Investment',
                'notes': 'Dell computers for development team'
            },
            {
                'description': 'Initial Capital Investment', 
                'capital_type': 'Cash Investment',
                'investment_date': '2026-01-01',
                'amount': 500000,
                'source': 'Founder Investment',
                'notes': 'Startup capital for business operations'
            }
        ])
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            sample_income.to_excel(writer, sheet_name='Income', index=False)
            sample_expenses.to_excel(writer, sheet_name='Expenses', index=False) 
            sample_capital.to_excel(writer, sheet_name='Capital', index=False)
            
            # Instructions sheet
            instructions_data = pd.DataFrame([
                {'Sheet': 'Income', 'Required Fields': 'description, contract_date, gross_amount', 'Optional Fields': 'vat_rate, customer_name, invoice_number'},
                {'Sheet': 'Expenses', 'Required Fields': 'description, expense_date, gross_amount', 'Optional Fields': 'vat_rate, supplier_name, receipt_number'},
                {'Sheet': 'Capital', 'Required Fields': 'description, investment_date, amount', 'Optional Fields': 'source, notes'}
            ])
            instructions_data.to_excel(writer, sheet_name='Instructions', index=False)
        
        return str(filepath)

__all__ = ['VATDataStore']