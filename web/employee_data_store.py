"""
Employee Data Store - Parquet-based persistence for Employee Management

Handles data persistence for employee records using Parquet files.
"""

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from datetime import datetime, date
from typing import Dict, List, Any, Optional
import uuid
import os
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


# Data directory for employee files
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Parquet file path
EMPLOYEE_PARQUET_FILE = DATA_DIR / 'employees.parquet'

class EmployeeDataStore:
    """Parquet-based data storage for employee records"""
    
    def __init__(self):
        self.schema = self._define_schema()
        self._initialize_data_file()
    
    def _define_schema(self) -> pa.Schema:
        """Define PyArrow schema for employee data"""
        return pa.schema([
            ('employee_id', pa.string()),
            ('company_id', pa.string()),
            ('name', pa.string()),
            ('category', pa.string()),
            ('basic_salary', pa.float64()),
            ('hire_date', pa.date32()),
            ('department', pa.string()),
            ('position', pa.string()),
            ('bank_account', pa.string()),
            ('tin_number', pa.string()),
            ('pension_number', pa.string()),
            ('work_days_per_month', pa.int32()),
            ('work_hours_per_day', pa.int32()),
            ('is_active', pa.bool_()),
            ('created_date', pa.timestamp('ns')),
            ('updated_date', pa.timestamp('ns'))
        ])
    
    def _initialize_data_file(self):
        """Create empty Parquet file if it doesn't exist"""
        if not EMPLOYEE_PARQUET_FILE.exists():
            try:
                # Create empty DataFrame with schema
                empty_df = pd.DataFrame({field.name: pd.Series(dtype=self._pa_to_pandas_dtype(field.type)) 
                                       for field in self.schema})
                
                # Ensure proper data types
                empty_df = self._ensure_dtypes(empty_df)
                
                # Write to parquet
                empty_df.to_parquet(EMPLOYEE_PARQUET_FILE, index=False)
                print(f"Created employees.parquet")
            except Exception as e:
                print(f"Warning: Could not create employees.parquet: {e}")
    
    def _pa_to_pandas_dtype(self, pa_type):
        """Convert PyArrow type to pandas dtype"""
        if pa.types.is_string(pa_type):
            return 'object'
        elif pa.types.is_float64(pa_type):
            return 'float64'
        elif pa.types.is_int32(pa_type):
            return 'int32'
        elif pa.types.is_date32(pa_type):
            return 'datetime64[ns]'
        elif pa.types.is_timestamp(pa_type):
            return 'datetime64[ns]'
        elif pa.types.is_boolean(pa_type):
            return 'bool'
        else:
            return 'object'
    
    def _ensure_dtypes(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure DataFrame has correct data types"""
        if 'hire_date' in df.columns:
            df['hire_date'] = pd.to_datetime(df['hire_date']).dt.date
        
        # Ensure timestamp columns
        for col in ['created_date', 'updated_date']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
        
        # Ensure boolean columns
        if 'is_active' in df.columns:
            df['is_active'] = df['is_active'].astype(bool)
        
        # Ensure integer columns with proper handling of NaN
        for col in ['work_days_per_month', 'work_hours_per_day']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(22 if col == 'work_days_per_month' else 8).astype('int32')
        
        # Ensure salary is float
        if 'basic_salary' in df.columns:
            df['basic_salary'] = pd.to_numeric(df['basic_salary'], errors='coerce').astype('float64')
        
        return df
    
    def _read_all_employees_unfiltered(self) -> pd.DataFrame:
        """Read ALL employee records across all companies (internal use for writes)."""
        if not EMPLOYEE_PARQUET_FILE.exists():
            return pd.DataFrame()
        try:
            df = pd.read_parquet(EMPLOYEE_PARQUET_FILE)
            if 'company_id' not in df.columns:
                df['company_id'] = 'default'
            return self._ensure_dtypes(df)
        except Exception as e:
            print(f"Error reading employees: {e}")
            return pd.DataFrame()

    def read_all_employees(self, company_id: str = None) -> pd.DataFrame:
        """Read all employee records for the current company."""
        try:
            df = self._read_all_employees_unfiltered()
            if df.empty:
                return df
            cid = _resolve_company_id(company_id)
            return df[df['company_id'] == cid].copy()
        except Exception as e:
            print(f"Error reading employees: {e}")
            return pd.DataFrame()
    
    def write_employees(self, df: pd.DataFrame):
        """Write employee DataFrame to Parquet file.
        
        NOTE: This writes ALL employees (all companies) since we read the
        full file, filter in memory, and merge back.
        """
        try:
            # Ensure company_id column exists
            if 'company_id' not in df.columns:
                df['company_id'] = 'default'
            # Ensure correct data types
            df = self._ensure_dtypes(df)
            
            # Write to parquet
            df.to_parquet(EMPLOYEE_PARQUET_FILE, index=False)
            
        except Exception as e:
            print(f"Error writing employees: {e}")
            raise
    
    def validate_employee_data(self, employee_data: dict, employee_id_to_exclude: str = None) -> List[str]:
        """Validate employee data and return list of errors"""
        errors = []
        
        # Check mandatory fields
        if not employee_data.get('employee_id', '').strip():
            errors.append('Employee ID is required')
        if not employee_data.get('name', '').strip():
            errors.append('Name is required')
        if not employee_data.get('tin_number', '').strip():
            errors.append('TIN Number is required')
        if not employee_data.get('category', '').strip():
            errors.append('Category is required')
        if not employee_data.get('basic_salary'):
            errors.append('Basic Salary is required')
        if not employee_data.get('hire_date'):
            errors.append('Hire Date is required')
        
        # Check for duplicates if we have the required fields
        employee_id = str(employee_data.get('employee_id', '')).strip()
        name = str(employee_data.get('name', '')).strip().lower()
        tin_number = str(employee_data.get('tin_number', '')).strip()
        
        if employee_id or name or tin_number:
            df = self.read_all_employees()
            
            if not df.empty:
                # Exclude current employee from duplicate check (for updates)
                if employee_id_to_exclude:
                    df = df[df['employee_id'] != employee_id_to_exclude]
                
                # Check Employee ID duplicate
                if employee_id and employee_id in df['employee_id'].values:
                    errors.append(f'Employee ID "{employee_id}" already exists')
                
                # Check Name duplicate (case-insensitive)
                if name and name in df['name'].str.lower().values:
                    errors.append(f'Employee name "{employee_data.get("name", "")}" already exists')
                
                # Check TIN duplicate
                if tin_number and tin_number in df['tin_number'].values:
                    errors.append(f'TIN Number "{tin_number}" already exists')
        
        return errors
        """Add a single employee record with validation"""
        # Validate employee data
        validation_errors = self.validate_employee_data(employee_data)
        if validation_errors:
            raise ValueError('Validation failed: ' + '; '.join(validation_errors))
        # Read existing data
        df = self.read_all_employees()
        
        # Add timestamps
        now = datetime.now()
        if 'created_date' not in employee_data:
            employee_data['created_date'] = now
        if 'updated_date' not in employee_data:
            employee_data['updated_date'] = now
        if 'is_active' not in employee_data:
            employee_data['is_active'] = True
        
        # Set defaults for optional fields
        employee_data.setdefault('bank_account', '')
        employee_data.setdefault('department', '')
        employee_data.setdefault('position', '')
        employee_data.setdefault('tin_number', '')
        employee_data.setdefault('pension_number', '')
        employee_data.setdefault('work_days_per_month', 22)
        employee_data.setdefault('work_hours_per_day', 8)
        
        # Create new row DataFrame
        new_row = pd.DataFrame([employee_data])
        
        # Append to existing data
        if not df.empty:
            df = pd.concat([df, new_row], ignore_index=True)
        else:
            df = new_row
        
        # Write back to file
        self.write_employees(df)
    
    def update_employee(self, employee_id: str, employee_data: dict):
        """Update an existing employee record with validation"""
        df = self._read_all_employees_unfiltered()
        
        if df.empty or employee_id not in df['employee_id'].values:
            raise ValueError(f'Employee {employee_id} not found')
        
        # Create complete employee data for validation (merge with existing data)
        existing_employee = df[df['employee_id'] == employee_id].iloc[0].to_dict()
        complete_data = {**existing_employee, **employee_data}
        complete_data['employee_id'] = employee_id  # Ensure employee_id doesn't change
        
        # Validate updated data (exclude current employee from duplicate checks)
        validation_errors = self.validate_employee_data(complete_data, employee_id_to_exclude=employee_id)
        if validation_errors:
            raise ValueError('Validation failed: ' + '; '.join(validation_errors))
        
        # Update the record
        mask = df['employee_id'] == employee_id
        for key, value in employee_data.items():
            if key in df.columns:
                df.loc[mask, key] = value
        
        # Update timestamp
        df.loc[mask, 'updated_date'] = datetime.now()
        
        # Write back to file
        self.write_employees(df)
    
    def get_employee(self, employee_id: str) -> Optional[Dict]:
        """Get a single employee by ID"""
        df = self.read_all_employees()
        
        if df.empty or employee_id not in df['employee_id'].values:
            return None
        
        employee_row = df[df['employee_id'] == employee_id].iloc[0]
        return employee_row.to_dict()
    
    def delete_employee(self, employee_id: str):
        """Soft delete an employee (set is_active to False)"""
        self.update_employee(employee_id, {'is_active': False})
    
    def employee_exists(self, employee_id: str) -> bool:
        """Check if an employee exists"""
        df = self.read_all_employees()
        return not df.empty and employee_id in df['employee_id'].values
    
    def get_active_employees(self, company_id: str = None) -> pd.DataFrame:
        """Get only active employees for the current company."""
        df = self.read_all_employees(company_id)
        if df.empty:
            return df
        return df[df['is_active'] == True]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get employee statistics"""
        df = self.read_all_employees()
        
        if df.empty:
            return {
                'total_employees': 0,
                'active_employees': 0,
                'total_salary_budget': 0,
                'avg_salary': 0,
                'by_category': {},
                'by_department': {}
            }
        
        active_df = df[df['is_active'] == True]
        
        stats = {
            'total_employees': len(df),
            'active_employees': len(active_df),
            'total_salary_budget': active_df['basic_salary'].sum() if not active_df.empty else 0,
            'avg_salary': active_df['basic_salary'].mean() if not active_df.empty else 0,
            'by_category': active_df.groupby('category')['employee_id'].count().to_dict() if not active_df.empty else {},
            'by_department': active_df.groupby('department')['employee_id'].count().to_dict() if not active_df.empty else {}
        }
        
        return stats
    
    def bulk_import(self, employees_data: List[Dict], overwrite: bool = False) -> Dict[str, Any]:
        """Bulk import employees from a list of dictionaries"""
        df = self._read_all_employees_unfiltered()
        
        success_count = 0
        error_count = 0
        errors = []
        
        for i, employee_data in enumerate(employees_data):
            try:
                employee_id = employee_data.get('employee_id', '').strip()
                
                # Validate employee data
                validation_errors = self.validate_employee_data(employee_data)
                if validation_errors:
                    errors.extend([f'Row {i + 1}: {error}' for error in validation_errors])
                    error_count += 1
                    continue
                
                # Check if employee exists for overwrite logic
                if self.employee_exists(employee_id) and not overwrite:
                    errors.append(f'Row {i + 1}: Employee {employee_id} already exists (use overwrite option)')
                    error_count += 1
                    continue
                
                # Add timestamps
                now = datetime.now()
                employee_data['created_date'] = now
                employee_data['updated_date'] = now
                
                # Set defaults
                employee_data.setdefault('is_active', True)
                employee_data.setdefault('company_id', _resolve_company_id())
                employee_data.setdefault('bank_account', '')
                employee_data.setdefault('department', '')
                employee_data.setdefault('position', '')
                employee_data.setdefault('tin_number', '')
                employee_data.setdefault('pension_number', '')
                employee_data.setdefault('work_days_per_month', 22)
                employee_data.setdefault('work_hours_per_day', 8)
                
                # If overwrite and exists, update existing record
                if overwrite and self.employee_exists(employee_id):
                    mask = df['employee_id'] == employee_id
                    for key, value in employee_data.items():
                        if key in df.columns:
                            df.loc[mask, key] = value
                else:
                    # Add new employee
                    new_row = pd.DataFrame([employee_data])
                    df = pd.concat([df, new_row], ignore_index=True) if not df.empty else new_row
                
                success_count += 1
                
            except Exception as e:
                errors.append(f"Row {i + 1}: {str(e)}")
                error_count += 1
        
        # Write all changes at once
        if success_count > 0:
            self.write_employees(df)
        
        return {
            'success_count': success_count,
            'error_count': error_count,
            'errors': errors
        }

__all__ = ['EmployeeDataStore']