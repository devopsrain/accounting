"""
Journal Entry Data Store - Parquet-based persistence for Journal Entries

Handles data persistence for journal entries and account transactions using Parquet files.
"""

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from datetime import datetime, date
from typing import Dict, List, Any, Optional
import uuid
import os


# Data directory for journal entry files
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Parquet file paths
JOURNAL_PARQUET_FILES = {
    'journal_entries': DATA_DIR / 'journal_entries.parquet',
    'journal_entry_lines': DATA_DIR / 'journal_entry_lines.parquet',
}


class JournalEntryDataStore:
    """Parquet-based data storage for journal entries"""
    
    def __init__(self):
        self.schemas = self._define_schemas()
        self._initialize_data_files()
    
    def _define_schemas(self) -> Dict[str, pa.Schema]:
        """Define PyArrow schemas for journal entry data"""
        return {
            'journal_entries': pa.schema([
                ('entry_id', pa.string()),
                ('company_id', pa.string()),
                ('entry_date', pa.string()),  # Store as string initially
                ('description', pa.string()),
                ('reference_number', pa.string()),
                ('total_debit', pa.float64()),
                ('total_credit', pa.float64()),
                ('created_by', pa.string()),
                ('created_date', pa.string()),  # Store as string initially
                ('status', pa.string()),
                ('is_active', pa.bool_())
            ]),
            'journal_entry_lines': pa.schema([
                ('line_id', pa.string()),
                ('entry_id', pa.string()),
                ('account_code', pa.string()),
                ('account_name', pa.string()),
                ('description', pa.string()),
                ('debit_amount', pa.float64()),
                ('credit_amount', pa.float64()),
                ('line_number', pa.int32()),
                ('created_date', pa.string()),  # Store as string initially
                ('is_active', pa.bool_())
            ])
        }
    
    def _initialize_data_files(self):
        """Initialize parquet files with schemas if they don't exist"""
        for table_name, filepath in JOURNAL_PARQUET_FILES.items():
            if not filepath.exists():
                schema = self.schemas[table_name]
                # Create empty dataframe with correct columns
                empty_data = {field.name: [] for field in schema}
                empty_df = pd.DataFrame(empty_data)
                
                # Convert to table with schema
                empty_table = pa.Table.from_pandas(empty_df, schema=schema)
                pq.write_table(empty_table, filepath)
    
    def read_journal_entries(self, company_id: str = None, 
                           start_date: Optional[date] = None,
                           end_date: Optional[date] = None) -> pd.DataFrame:
        """Read journal entries with optional filters"""
        filters = []
        
        if company_id:
            filters.append(('company_id', '==', company_id))
        
        filters.append(('is_active', '==', True))
        
        if start_date:
            filters.append(('entry_date', '>=', start_date))
        if end_date:
            filters.append(('entry_date', '<=', end_date))
        
        try:
            table = pq.read_table(JOURNAL_PARQUET_FILES['journal_entries'], filters=filters)
            return table.to_pandas()
        except:
            return pd.DataFrame()
    
    def read_entry_lines(self, entry_id: str = None) -> pd.DataFrame:
        """Read journal entry lines"""
        filters = [('is_active', '==', True)]
        
        if entry_id:
            filters.append(('entry_id', '==', entry_id))
        
        try:
            table = pq.read_table(JOURNAL_PARQUET_FILES['journal_entry_lines'], filters=filters)
            return table.to_pandas()
        except:
            return pd.DataFrame()
    
    def save_journal_entry(self, entry_data: Dict[str, Any], lines_data: List[Dict[str, Any]]) -> str:
        """Save a complete journal entry with its lines"""
        entry_id = entry_data.get('entry_id', str(uuid.uuid4()))
        
        # Prepare entry data
        entry_record = {
            'entry_id': entry_id,
            'company_id': entry_data.get('company_id', 'default'),
            'entry_date': str(entry_data.get('entry_date', date.today())),
            'description': entry_data.get('description', ''),
            'reference_number': entry_data.get('reference_number', ''),
            'total_debit': entry_data.get('total_debit', 0.0),
            'total_credit': entry_data.get('total_credit', 0.0),
            'created_by': entry_data.get('created_by', 'system'),
            'created_date': str(date.today()),
            'status': entry_data.get('status', 'posted'),
            'is_active': True
        }
        
        # Save entry
        entry_df = pd.DataFrame([entry_record])
        self._append_to_table('journal_entries', entry_df)
        
        # Prepare and save lines
        for i, line in enumerate(lines_data):
            line_record = {
                'line_id': str(uuid.uuid4()),
                'entry_id': entry_id,
                'account_code': line.get('account_code', ''),
                'account_name': line.get('account_name', ''),
                'description': line.get('description', ''),
                'debit_amount': float(line.get('debit_amount', 0)),
                'credit_amount': float(line.get('credit_amount', 0)),
                'line_number': i + 1,
                'created_date': str(date.today()),
                'is_active': True
            }
            
            line_df = pd.DataFrame([line_record])
            self._append_to_table('journal_entry_lines', line_df)
        
        return entry_id
    
    def _append_to_table(self, table_name: str, df: pd.DataFrame):
        """Append data to existing parquet table"""
        filepath = JOURNAL_PARQUET_FILES[table_name]
        
        # Read existing data
        try:
            existing_table = pq.read_table(filepath)
            existing_df = existing_table.to_pandas()
            
            # Append new data
            updated_df = pd.concat([existing_df, df], ignore_index=True)
        except:
            updated_df = df
        
        # Write updated data
        table = pa.Table.from_pandas(updated_df, schema=self.schemas[table_name])
        pq.write_table(table, filepath)
    
    def bulk_import_entries(self, entries_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Bulk import journal entries from Excel data"""
        result = {'success': False, 'imported_count': 0, 'errors': []}
        
        try:
            for i, entry in enumerate(entries_data):
                try:
                    # Validate entry structure
                    if not self._validate_journal_entry(entry):
                        result['errors'].append(f'Invalid entry structure at row {i+1}')
                        continue
                    
                    # Extract lines from entry
                    lines = entry.get('lines', [])
                    if not lines:
                        result['errors'].append(f'No lines found for entry at row {i+1}')
                        continue
                    
                    # Save entry
                    entry_id = self.save_journal_entry(entry, lines)
                    result['imported_count'] += 1
                    
                except Exception as e:
                    result['errors'].append(f'Error importing entry {i+1}: {str(e)}')
            
            result['success'] = True
            
        except Exception as e:
            result['errors'].append(f'Bulk import error: {str(e)}')
        
        return result
    
    def _validate_journal_entry(self, entry: Dict[str, Any]) -> bool:
        """Validate journal entry data"""
        required_fields = ['description', 'entry_date']
        
        for field in required_fields:
            if field not in entry or not entry[field]:
                return False
        
        # Validate lines
        lines = entry.get('lines', [])
        if not lines:
            return False
        
        total_debits = sum(float(line.get('debit_amount', 0)) for line in lines)
        total_credits = sum(float(line.get('credit_amount', 0)) for line in lines)
        
        # Check if debits equal credits
        return abs(total_debits - total_credits) < 0.01
    
    def export_to_excel(self, company_id: str = None, filename: str = None) -> str:
        """Export journal entries to Excel"""
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            company_str = f'_{company_id}' if company_id else ''
            filename = f'journal_entries{company_str}_{timestamp}.xlsx'
        
        filepath = DATA_DIR / filename
        
        # Get journal entries and lines
        entries_df = self.read_journal_entries(company_id)
        lines_df = self.read_entry_lines()
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            # Export entries
            if not entries_df.empty:
                entries_export = entries_df.copy()
                entries_export = entries_export.drop(['company_id', 'is_active'], axis=1, errors='ignore')
                entries_export.to_excel(writer, sheet_name='Journal Entries', index=False)
            
            # Export lines
            if not lines_df.empty:
                lines_export = lines_df.copy()
                lines_export = lines_export.drop(['is_active'], axis=1, errors='ignore')
                lines_export.to_excel(writer, sheet_name='Entry Lines', index=False)
            
            # Create template sheet
            template_data = pd.DataFrame([
                {
                    'entry_date': '2026-02-19',
                    'description': 'Sample Journal Entry',
                    'reference_number': 'JE-2026-001',
                    'account_code_1': '1000',
                    'account_name_1': 'Cash',
                    'debit_1': 10000,
                    'credit_1': 0,
                    'account_code_2': '4000', 
                    'account_name_2': 'Revenue',
                    'debit_2': 0,
                    'credit_2': 10000
                }
            ])
            template_data.to_excel(writer, sheet_name='Import Template', index=False)
        
        return str(filepath)
    
    def import_from_excel(self, excel_file: str, company_id: str = 'default') -> Dict[str, Any]:
        """Import journal entries from Excel file"""
        result = {'success': False, 'imported_count': 0, 'errors': []}
        
        try:
            # Try to read the import template sheet
            df = pd.read_excel(excel_file, sheet_name='Import Template')
            
            entries_to_import = []
            
            for _, row in df.iterrows():
                try:
                    # Parse journal entry from row
                    entry = {
                        'company_id': company_id,
                        'entry_date': row.get('entry_date'),
                        'description': row.get('description', ''),
                        'reference_number': row.get('reference_number', ''),
                        'lines': []
                    }
                    
                    # Extract line items (assuming up to 10 lines per entry)
                    total_debit = 0
                    total_credit = 0
                    
                    for i in range(1, 11):  # Support up to 10 lines
                        account_code = row.get(f'account_code_{i}')
                        debit = row.get(f'debit_{i}', 0)
                        credit = row.get(f'credit_{i}', 0)
                        
                        if account_code and (debit or credit):
                            line = {
                                'account_code': str(account_code),
                                'account_name': row.get(f'account_name_{i}', ''),
                                'description': row.get(f'line_description_{i}', entry['description']),
                                'debit_amount': float(debit) if debit else 0,
                                'credit_amount': float(credit) if credit else 0
                            }
                            
                            entry['lines'].append(line)
                            total_debit += line['debit_amount']
                            total_credit += line['credit_amount']
                    
                    entry['total_debit'] = total_debit
                    entry['total_credit'] = total_credit
                    
                    entries_to_import.append(entry)
                    
                except Exception as e:
                    result['errors'].append(f'Error parsing row: {str(e)}')
            
            # Import entries
            import_result = self.bulk_import_entries(entries_to_import)
            result.update(import_result)
            
        except Exception as e:
            result['errors'].append(f'Excel import error: {str(e)}')
        
        return result
    
    def create_sample_excel_file(self, filename: str = None) -> str:
        """Create sample Excel file for journal entries"""
        if filename is None:
            filename = 'journal_entries_sample_data.xlsx'
        
        filepath = DATA_DIR / filename
        
        sample_entries = pd.DataFrame([
            {
                'entry_date': '2026-01-15',
                'description': 'Initial Cash Investment',
                'reference_number': 'JE-2026-001',
                'account_code_1': '1000',
                'account_name_1': 'Cash',
                'debit_1': 100000,
                'credit_1': 0,
                'account_code_2': '3000',
                'account_name_2': 'Capital',
                'debit_2': 0,
                'credit_2': 100000
            },
            {
                'entry_date': '2026-01-20',
                'description': 'Office Equipment Purchase',
                'reference_number': 'JE-2026-002', 
                'account_code_1': '1500',
                'account_name_1': 'Office Equipment',
                'debit_1': 25000,
                'credit_1': 0,
                'account_code_2': '1000',
                'account_name_2': 'Cash',
                'debit_2': 0,
                'credit_2': 25000
            },
            {
                'entry_date': '2026-01-25',
                'description': 'Service Revenue Recognition',
                'reference_number': 'JE-2026-003',
                'account_code_1': '1200',
                'account_name_1': 'Accounts Receivable',
                'debit_1': 50000,
                'credit_1': 0,
                'account_code_2': '4000',
                'account_name_2': 'Service Revenue',
                'debit_2': 0,
                'credit_2': 50000
            }
        ])
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            sample_entries.to_excel(writer, sheet_name='Import Template', index=False)
            
            # Instructions
            instructions = pd.DataFrame([
                {'Field': 'entry_date', 'Description': 'Date of journal entry (YYYY-MM-DD)', 'Required': 'Yes'},
                {'Field': 'description', 'Description': 'Entry description', 'Required': 'Yes'},
                {'Field': 'reference_number', 'Description': 'Reference number or document ID', 'Required': 'No'},
                {'Field': 'account_code_X', 'Description': 'Account code for line X (1-10)', 'Required': 'Yes'},
                {'Field': 'account_name_X', 'Description': 'Account name for line X', 'Required': 'No'},
                {'Field': 'debit_X', 'Description': 'Debit amount for line X', 'Required': 'For debit entries'},
                {'Field': 'credit_X', 'Description': 'Credit amount for line X', 'Required': 'For credit entries'},
            ])
            instructions.to_excel(writer, sheet_name='Instructions', index=False)
        
        return str(filepath)

__all__ = ['JournalEntryDataStore']