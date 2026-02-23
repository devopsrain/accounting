"""
Ethiopian Payroll Web Interface

Flask routes and templates for Ethiopian payroll management
"""

from datetime import datetime, date, timedelta
import calendar
import logging
from flask import render_template, request, redirect, url_for, flash, jsonify
from models.ethiopian_payroll import (
    Employee, EmployeeCategory, EthiopianPayrollCalculator,
    PayrollItem, AllowanceType, DeductionType
)
from core.ethiopian_payroll_integration import EthiopianPayrollIntegration
from payroll_demo_data import add_demo_payroll_data
from employee_data_store import EmployeeDataStore
import json

logger = logging.getLogger(__name__)


def add_payroll_routes(app, ledger):
    """Add Ethiopian payroll routes to Flask app"""
    
    payroll_integration = EthiopianPayrollIntegration(ledger)
    
    # Use persistent storage for employees
    employee_store = EmployeeDataStore()

    # ── Helper: build Employee from a dict/row ────────────────────────
    def _normalize_hire_date(raw):
        """Convert various hire-date representations to a date object."""
        if isinstance(raw, str):
            return datetime.strptime(raw, '%Y-%m-%d').date()
        if hasattr(raw, 'date') and callable(raw.date):
            return raw.date()
        if isinstance(raw, date):
            return raw
        return date.today()  # fallback

    def _build_employee(data) -> Employee:
        """Build an Employee from a dict (data-store row or DataFrame row).

        Centralises the 14-field Employee construction that was previously
        copy-pasted 6+ times across payroll routes.
        """
        return Employee(
            employee_id=data['employee_id'],
            name=data['name'],
            category=EmployeeCategory(data['category']),
            basic_salary=float(data.get('basic_salary', 0) or 0),
            hire_date=_normalize_hire_date(data.get('hire_date', date.today())),
            department=data.get('department', ''),
            position=data.get('position', ''),
            bank_account=data.get('bank_account', ''),
            tin_number=data.get('tin_number', ''),
            pension_number=data.get('pension_number', ''),
            work_days_per_month=int(data.get('work_days_per_month', 22) or 22),
            work_hours_per_day=int(data.get('work_hours_per_day', 8) or 8),
            is_active=bool(data.get('is_active', True)),
        )
    
    # Flag to track if demo data has been loaded
    demo_data_loaded = False
    
    def ensure_demo_data():
        """Load demo data if not already loaded"""
        nonlocal demo_data_loaded
        if not demo_data_loaded:
            # Check if we already have employees in persistent storage
            df = employee_store.read_all_employees()
            if df.empty:
                # Load demo data into temporary dict then import to persistent storage
                temp_employees_db = {}
                add_demo_payroll_data(temp_employees_db)
                
                # Convert to list of dicts for bulk import
                employees_data = []
                for emp in temp_employees_db.values():
                    emp_dict = {
                        'employee_id': emp.employee_id,
                        'name': emp.name,
                        'category': emp.category.value,
                        'basic_salary': emp.basic_salary,
                        'hire_date': emp.hire_date,
                        'department': emp.department,
                        'position': emp.position,
                        'bank_account': emp.bank_account,
                        'tin_number': emp.tin_number,
                        'pension_number': emp.pension_number,
                        'work_days_per_month': emp.work_days_per_month,
                        'work_hours_per_day': emp.work_hours_per_day,
                        'is_active': emp.is_active
                    }
                    employees_data.append(emp_dict)
                
                # Bulk import to persistent storage
                result = employee_store.bulk_import(employees_data, overwrite=True)
                print(f"✓ Loaded {result['success_count']} demo employees to persistent storage")
                
            demo_data_loaded = True
    
    @app.route('/payroll')
    def payroll_dashboard():
        """Payroll dashboard"""
        ensure_demo_data()
        df = employee_store.get_active_employees()
        employee_count = len(df)
        # Convert to dict format for template compatibility
        employees_dict = {}
        if not df.empty:
            for _, row in df.iterrows():
                employees_dict[row['employee_id']] = row.to_dict()
        return render_template('payroll/dashboard.html', 
                             employees=employees_dict, 
                             employee_count=employee_count)
    
    @app.route('/payroll/employees')
    def employees_list():
        """List all employees"""
        ensure_demo_data()
        df = employee_store.read_all_employees()
        # Convert to dict format for template compatibility
        employees_dict = {}
        if not df.empty:
            for _, row in df.iterrows():
                # Convert employee data to Employee object for template
                try:
                    emp = _build_employee(row)
                    employees_dict[row['employee_id']] = emp
                except Exception as e:
                    print(f"Error converting employee {row.get('employee_id', 'unknown')}: {e}")
        return render_template('payroll/employees.html', employees=employees_dict)
    
    @app.route('/payroll/employees/add', methods=['GET', 'POST'])
    def add_employee():
        """Add new employee"""
        if request.method == 'POST':
            try:
                employee_id = request.form['employee_id']
                
                if employee_store.employee_exists(employee_id):
                    flash('Employee ID already exists!', 'error')
                    return render_template('payroll/add_employee.html', categories=EmployeeCategory)
                
                # Prepare employee data
                employee_data = {
                    'employee_id': employee_id,
                    'name': request.form['name'],
                    'category': request.form['category'],
                    'basic_salary': float(request.form['basic_salary']),
                    'hire_date': datetime.strptime(request.form['hire_date'], '%Y-%m-%d').date(),
                    'department': request.form.get('department', ''),
                    'position': request.form.get('position', ''),
                    'tin_number': request.form.get('tin_number', '').strip(),
                    'pension_number': request.form.get('pension_number', '')
                }
                
                # Validate TIN is provided
                if not employee_data['tin_number']:
                    flash('TIN Number is required!', 'error')
                    return render_template('payroll/add_employee.html', categories=EmployeeCategory)
                
                employee_store.add_employee(employee_data)
                flash('Employee added successfully!', 'success')
                return redirect(url_for('employees_list'))
                
            except Exception as e:
                flash(f'Error adding employee: {str(e)}', 'error')
        
        return render_template('payroll/add_employee.html', categories=EmployeeCategory)
    
    @app.route('/payroll/employees/<employee_id>/edit', methods=['GET', 'POST'])
    def edit_employee(employee_id):
        """Edit employee"""
        employee_data = employee_store.get_employee(employee_id)
        if not employee_data:
            flash('Employee not found!', 'error')
            return redirect(url_for('employees_list'))
        
        if request.method == 'POST':
            try:
                # Prepare updated data
                updated_data = {
                    'name': request.form['name'],
                    'category': request.form['category'],
                    'basic_salary': float(request.form['basic_salary']),
                    'hire_date': datetime.strptime(request.form['hire_date'], '%Y-%m-%d').date(),
                    'department': request.form.get('department', ''),
                    'position': request.form.get('position', ''),
                    'tin_number': request.form.get('tin_number', '').strip(),
                    'pension_number': request.form.get('pension_number', ''),
                    'is_active': 'is_active' in request.form
                }
                
                # Validate TIN is provided
                if not updated_data['tin_number']:
                    flash('TIN Number is required!', 'error')
                    employee_data = employee_store.get_employee(employee_id)
                    employee = _build_employee(employee_data)
                    return render_template('payroll/edit_employee.html', employee=employee, categories=EmployeeCategory)
                
                employee_store.update_employee(employee_id, updated_data)
                flash('Employee updated successfully!', 'success')
                return redirect(url_for('employees_list'))
                
            except Exception as e:
                flash(f'Error updating employee: {str(e)}', 'error')
        
        # Convert to Employee object for form display
        try:
            employee = _build_employee(employee_data)
        except Exception as e:
            flash(f'Error loading employee data: {str(e)}', 'error')
            return redirect(url_for('employees_list'))
        
        return render_template('payroll/edit_employee.html', employee=employee, categories=EmployeeCategory)
    
    @app.route('/payroll/calculate', methods=['GET', 'POST'])
    def calculate_payroll():
        """Calculate payroll for active employees"""
        if request.method == 'POST':
            try:
                pay_period_start = datetime.strptime(request.form['pay_period_start'], '%Y-%m-%d').date()
                pay_period_end = datetime.strptime(request.form['pay_period_end'], '%Y-%m-%d').date()
                
                active_employees = []
                df = employee_store.get_active_employees()
                if not df.empty:
                    for _, row in df.iterrows():
                        try:
                            emp = _build_employee(row)
                            hire_date = emp.hire_date
                            
                            # Only include employees hired before or during the pay period
                            if hire_date <= pay_period_end:
                                active_employees.append(emp)
                            else:
                                print(f"Employee {emp.name} excluded - hired after pay period ({hire_date})")
                                
                        except Exception as e:
                            employee_id = row.get('employee_id', 'unknown')
                            print(f"Error converting employee {employee_id}: {e}")
                            flash(f'Warning: Could not process employee {employee_id}: {str(e)}', 'warning')
                
                if not active_employees:
                    flash('No active employees found!', 'error')
                    return render_template('payroll/calculate.html')
                
                # Process payroll
                result = payroll_integration.process_monthly_payroll(
                    active_employees, pay_period_start, pay_period_end
                )
                
                payroll_summary = result['payroll_summary']
                payroll_items = result['payroll_items']
                
                flash(f'Payroll processed successfully for {payroll_summary["total_employees"]} employees!', 'success')
                
                return render_template('payroll/calculate_result.html',
                                     summary=payroll_summary,
                                     payroll_items=payroll_items,
                                     journal_entries=result['journal_entries'])
                
            except Exception as e:
                flash(f'Error processing payroll: {str(e)}', 'error')
        
        # Default to current month or January 2026 if employees exist with Jan 2026 hire dates
        today = date.today()
        
        # Check if employees were hired in January 2026 and set appropriate default period
        df = employee_store.get_active_employees()
        default_year = today.year
        default_month = today.month
        
        if not df.empty:
            # Check if most employees were hired in January 2026
            jan_2026_hires = 0
            for _, row in df.iterrows():
                hire_date = row['hire_date']
                if isinstance(hire_date, str):
                    hire_date = datetime.strptime(hire_date, '%Y-%m-%d').date()
                if hire_date.year == 2026 and hire_date.month == 1:
                    jan_2026_hires += 1
            
            # If majority hired in Jan 2026, default to January 2026
            if jan_2026_hires > len(df) / 2:
                default_year = 2026
                default_month = 1
        
        start_of_month = date(default_year, default_month, 1)
        last_day = calendar.monthrange(default_year, default_month)[1]
        end_of_month = date(default_year, default_month, last_day)
        
        # Get active employees for display
        active_employees_list = []
        df = employee_store.get_active_employees()
        if not df.empty:
            for _, row in df.iterrows():
                try:
                    emp = _build_employee(row)
                    active_employees_list.append(emp)
                except Exception as e:
                    employee_id = row.get('employee_id', 'unknown')
                    print(f"Error converting employee {employee_id}: {e}")
    
        return render_template('payroll/calculate.html',
                             default_start=start_of_month,
                             default_end=end_of_month,
                             active_employees=active_employees_list)
    
    @app.route('/payroll/employees/<employee_id>/payslip')
    def generate_payslip(employee_id):
        """Generate payslip for individual employee"""
        employee_data = employee_store.get_employee(employee_id)
        if not employee_data:
            flash('Employee not found!', 'error')
            return redirect(url_for('employees_list'))
        
        # Convert to Employee object
        try:
            employee = _build_employee(employee_data)
        except Exception as e:
            flash(f'Error loading employee data: {str(e)}', 'error')
            return redirect(url_for('employees_list'))
        
        # Generate payslip for current month
        today = date.today()
        pay_period_start = date(today.year, today.month, 1)
        pay_period_end = date(today.year, today.month, 28)
        
        calculator = EthiopianPayrollCalculator()
        
        payroll_item = PayrollItem(
            employee=employee,
            pay_period_start=pay_period_start,
            pay_period_end=pay_period_end
        )
        
        # Add some sample allowances (in a real system, these would come from database)
        if employee.basic_salary > 10000:
            payroll_item.add_allowance(AllowanceType.TRANSPORT, 600, False, "Transport allowance")
            payroll_item.add_allowance(AllowanceType.HOUSING, min(employee.basic_salary * 0.2, 5000), True, "Housing allowance")
        
        calculated_item = calculator.calculate_payroll_item(payroll_item)
        payslip = calculator.generate_pay_slip(calculated_item)
        
        return render_template('payroll/payslip.html', payslip=payslip, employee=employee)
    
    @app.route('/payroll/reports')
    def payroll_reports():
        """Payroll reports"""
        # Get report for current month
        today = date.today()
        start_of_month = date(today.year, today.month, 1)
        end_of_month = date(today.year, today.month, 28)
        
        report = payroll_integration.get_payroll_reports(start_of_month, end_of_month)
        
        return render_template('payroll/reports.html', 
                             report=report,
                             period_start=start_of_month,
                             period_end=end_of_month)
    
    @app.route('/api/payroll/tax-calculator', methods=['POST'])
    def tax_calculator_api():
        """API endpoint for tax calculation"""
        try:
            data = request.get_json()
            taxable_income = float(data.get('taxable_income', 0))
            
            calculator = EthiopianPayrollCalculator()
            tax_amount = calculator.calculate_income_tax(taxable_income)
            
            return jsonify({
                'taxable_income': taxable_income,
                'tax_amount': tax_amount,
                'effective_rate': (tax_amount / taxable_income * 100) if taxable_income > 0 else 0,
                'net_income': taxable_income - tax_amount
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 400
    
    @app.route('/payroll/tax-calculator')
    def tax_calculator():
        """Tax calculator tool"""
        calculator = EthiopianPayrollCalculator()
        return render_template('payroll/tax_calculator.html', 
                             tax_brackets=calculator.INCOME_TAX_BRACKETS)
    
    @app.route('/payroll/employees/export-excel')
    def export_employees_excel():
        """Export all employees to Excel file"""
        try:
            import pandas as pd
            from flask import make_response
            from datetime import datetime
            from io import BytesIO
            
            ensure_demo_data()
            
            # Get employee data from persistent storage
            df = employee_store.read_all_employees()
            
            if df.empty:
                flash('No employees found to export!', 'warning')
                return redirect(url_for('employees_list'))
            
            # Prepare data for Excel export
            employee_data = []
            for _, row in df.iterrows():
                employee_data.append({
                    'Employee ID': row['employee_id'],
                    'Name': row['name'],
                    'Category': row['category'],
                    'Basic Salary': row['basic_salary'],
                    'Hire Date': row['hire_date'].strftime('%Y-%m-%d') if hasattr(row['hire_date'], 'strftime') else str(row['hire_date']),
                    'Department': row.get('department', ''),
                    'Position': row.get('position', ''),
                    'TIN Number': row.get('tin_number', ''),
                    'Pension Number': row.get('pension_number', ''),
                    'Work Days/Month': row.get('work_days_per_month', 22),
                    'Work Hours/Day': row.get('work_hours_per_day', 8),
                    'Active': 'Yes' if row.get('is_active', True) else 'No'
                })
            
            # Create DataFrame
            df = pd.DataFrame(employee_data)
            
            # Create Excel file in memory
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Employees', index=False)
                
                # Get the workbook and worksheet
                workbook = writer.book
                worksheet = writer.sheets['Employees']
                
                # Auto-adjust column widths
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
            
            output.seek(0)
            
            # Create response
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            response.headers['Content-Disposition'] = f'attachment; filename=employees_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
            
            flash('Employees exported successfully!', 'success')
            return response
            
        except Exception as e:
            flash(f'Error exporting employees: {str(e)}', 'error')
            return redirect(url_for('employees_list'))
    
    @app.route('/payroll/employees/download-template')
    def download_employee_template():
        """Download Excel template for employee import"""
        try:
            import pandas as pd
            from flask import make_response
            from io import BytesIO
            
            # Template data with sample row and instructions
            template_data = [
                {
                    'Employee ID': 'EMP001',
                    'Name': 'John Doe',
                    'Category': 'Regular Employee',
                    'Basic Salary': 12000,
                    'Hire Date': '2026-01-15',
                    'Department': 'Finance',
                    'Position': 'Accountant',
                    'TIN Number': 'TIN123456789',
                    'Pension Number': 'PEN987654321',
                    'Work Days/Month': 22,
                    'Work Hours/Day': 8,
                    'Active': 'Yes'
                }
            ]
            
            df = pd.DataFrame(template_data)
            
            # Create Excel file in memory
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Employee Template', index=False)
                
                # Add instructions sheet
                instructions = pd.DataFrame({
                    'Field': ['Employee ID', 'Name', 'Category', 'Basic Salary', 'Hire Date', 'TIN Number', 'Department', 'Position', 'Pension Number', 'Work Days/Month', 'Work Hours/Day', 'Active'],
                    'Description': [
                        'Unique employee identifier (required)',
                        'Full employee name (required)',
                        'Employee category: Regular Employee, Contract Employee, Casual Worker, Executive (required)',
                        'Monthly basic salary amount (required)',
                        'Hire date in YYYY-MM-DD format (required)',
                        'Tax identification number (required)',
                        'Department name',
                        'Job position/title',
                        'Pension scheme number',
                        'Working days per month (default: 22)',
                        'Working hours per day (default: 8)',
                        'Employee status: Yes or No (default: Yes)'
                    ],
                    'Required': ['Yes', 'Yes', 'Yes', 'Yes', 'Yes', 'Yes', 'No', 'No', 'No', 'No', 'No', 'No']
                })
                instructions.to_excel(writer, sheet_name='Instructions', index=False)
                
                # Auto-adjust column widths for both sheets
                for sheet_name in writer.sheets:
                    worksheet = writer.sheets[sheet_name]
                    for column in worksheet.columns:
                        max_length = 0
                        column_letter = column[0].column_letter
                        for cell in column:
                            try:
                                if len(str(cell.value)) > max_length:
                                    max_length = len(str(cell.value))
                            except:
                                pass
                        adjusted_width = min(max_length + 2, 50)
                        worksheet.column_dimensions[column_letter].width = adjusted_width
            
            output.seek(0)
            
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            response.headers['Content-Disposition'] = 'attachment; filename=employee_import_template.xlsx'
            
            return response
            
        except Exception as e:
            flash(f'Error generating template: {str(e)}', 'error')
            return redirect(url_for('employees_list'))
    
    @app.route('/payroll/employees/import-excel', methods=['GET', 'POST'])
    def import_employees_excel():
        """Import employees from Excel file"""
        if request.method == 'POST':
            try:
                import pandas as pd
                from werkzeug.utils import secure_filename
                import os
                
                # Check if file was uploaded
                if 'excel_file' not in request.files:
                    flash('No file selected!', 'error')
                    return redirect(request.url)
                
                file = request.files['excel_file']
                if file.filename == '':
                    flash('No file selected!', 'error')
                    return redirect(request.url)
                
                if not file.filename.lower().endswith(('.xlsx', '.xls')):
                    flash('Please upload an Excel file (.xlsx or .xls)', 'error')
                    return redirect(request.url)
                
                # Read Excel file
                df = pd.read_excel(file, sheet_name=0)  # Read first sheet
                
                # Validate required columns
                required_columns = ['Employee ID', 'Name', 'Category', 'Basic Salary', 'Hire Date', 'TIN Number']
                missing_columns = [col for col in required_columns if col not in df.columns]
                if missing_columns:
                    flash(f'Missing required columns: {", ".join(missing_columns)}', 'error')
                    return redirect(request.url)
                
                # Process each row
                success_count = 0
                error_count = 0
                errors = []
                
                employees_to_import = []
                
                for index, row in df.iterrows():
                    try:
                        # Skip empty rows (check all required fields)
                        if (pd.isna(row['Employee ID']) or pd.isna(row['Name']) or 
                            pd.isna(row['TIN Number']) or str(row['TIN Number']).strip() == ''):
                            errors.append(f"Row {index + 2}: Missing required fields (Employee ID, Name, or TIN Number)")
                            error_count += 1
                            continue
                        
                        employee_id = str(row['Employee ID']).strip()
                        name = str(row['Name']).strip()
                        tin_number = str(row['TIN Number']).strip()
                        
                        # Validate required fields are not empty
                        if not employee_id or not name or not tin_number:
                            errors.append(f"Row {index + 2}: Employee ID, Name, and TIN Number are required")
                            error_count += 1
                            continue
                        
                        # Check if employee already exists
                        overwrite = request.form.get('overwrite') == 'on'
                        if employee_store.employee_exists(employee_id) and not overwrite:
                            errors.append(f"Row {index + 2}: Employee {employee_id} already exists (use overwrite option)")
                            error_count += 1
                            continue
                        
                        # Map category string to enum
                        category_mapping = {
                            'Regular Employee': 'Regular Employee',
                            'Contract Employee': 'Contract Employee',
                            'Casual Worker': 'Casual Worker',
                            'Executive': 'Executive'
                        }
                        
                        category_str = str(row['Category']).strip()
                        if category_str not in category_mapping:
                            errors.append(f"Row {index + 2}: Invalid category '{category_str}'")
                            error_count += 1
                            continue
                        
                        # Parse hire date
                        hire_date = pd.to_datetime(row['Hire Date']).date()
                        
                        # Prepare employee data
                        employee_data = {
                            'employee_id': employee_id,
                            'name': name,
                            'category': category_mapping[category_str],
                            'basic_salary': float(row['Basic Salary']),
                            'hire_date': hire_date,
                            'department': str(row.get('Department', '')).strip(),
                            'position': str(row.get('Position', '')).strip(),
                            'tin_number': tin_number,
                            'pension_number': str(row.get('Pension Number', '')).strip(),
                            'work_days_per_month': int(row.get('Work Days/Month', 22)),
                            'work_hours_per_day': int(row.get('Work Hours/Day', 8)),
                            'is_active': str(row.get('Active', 'Yes')).strip().lower() in ['yes', '1', 'true', 'active']
                        }
                        
                        employees_to_import.append(employee_data)
                        
                    except Exception as e:
                        errors.append(f"Row {index + 2}: {str(e)}")
                        error_count += 1
                
                # Bulk import employees
                if employees_to_import:
                    overwrite = request.form.get('overwrite') == 'on'
                    result = employee_store.bulk_import(employees_to_import, overwrite)
                    success_count = result['success_count']
                    if result['errors']:
                        errors.extend(result['errors'])
                        error_count += result['error_count']
                
                # Show results
                if success_count > 0:
                    flash(f'Successfully imported {success_count} employees!', 'success')
                
                if error_count > 0:
                    error_msg = f'Failed to import {error_count} employees. Errors: ' + '; '.join(errors[:5])
                    if len(errors) > 5:
                        error_msg += f' (and {len(errors) - 5} more...)'
                    flash(error_msg, 'error')
                
                # SIEM: Log upload event
                try:
                    from siem_data_store import siem_store
                    siem_store.log_upload_event(
                        request, module='payroll', endpoint='/payroll/employees/import-excel',
                        filename=file.filename,
                        records_imported=success_count,
                        status='success' if success_count > 0 and error_count == 0 else ('partial' if success_count > 0 else 'failed'),
                        details=f"Imported {success_count} employees, {error_count} errors"
                    )
                except Exception as e:
                    logger.warning("SIEM logging failed: %s", e)
                
                return redirect(url_for('employees_list'))
                
            except Exception as e:
                # SIEM: Log exception
                try:
                    from siem_data_store import siem_store
                    siem_store.log_upload_event(
                        request, module='payroll', endpoint='/payroll/employees/import-excel',
                        filename=file.filename if 'file' in dir() else '',
                        status='failed', details=str(e)
                    )
                except Exception as e2:
                    logger.warning("SIEM logging failed: %s", e2)
                flash(f'Error importing file: {str(e)}', 'error')
                return redirect(request.url)
        
        return render_template('payroll/import_employees.html')