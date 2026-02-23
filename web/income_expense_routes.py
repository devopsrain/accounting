"""
Income & Expense Management Routes

Flask routes for income and expense management with Excel import/export functionality
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file, make_response
from datetime import datetime, date
import logging
import tempfile
import os
from decimal import Decimal

from income_expense_data_store import IncomeExpenseDataStore

logger = logging.getLogger(__name__)

# Create blueprint
income_expense_bp = Blueprint('income_expense', __name__, url_prefix='/income-expense')

# Create data store
income_expense_store = IncomeExpenseDataStore()


def get_current_month_salary_data():
    """Get current month salary data from payroll system"""
    try:
        import pandas as pd
        import os
        from datetime import datetime, date
        
        # Try to read payroll data
        payroll_file = os.path.join('data', 'employees.parquet')
        if not os.path.exists(payroll_file):
            return {'total_salary_expense': 0, 'employee_count': 0, 'message': 'No payroll data available'}
        
        # Load employee data
        df = pd.read_parquet(payroll_file)
        if df.empty:
            return {'total_salary_expense': 0, 'employee_count': 0, 'message': 'No employees found'}
        
        # Calculate total monthly salary expense
        active_employees = df[df.get('active', True) == True] if 'active' in df.columns else df
        total_salary = active_employees['basic_salary'].sum() if 'basic_salary' in active_employees.columns else 0
        
        # Add employer costs (pension 11%, estimated benefits 5%)
        employer_costs = total_salary * 0.16  # 11% pension + 5% benefits
        total_salary_expense = total_salary + employer_costs
        
        return {
            'total_salary_expense': float(total_salary_expense),
            'employee_count': len(active_employees),
            'base_salary': float(total_salary),
            'employer_costs': float(employer_costs),
            'message': 'Current month salary expense'
        }
        
    except Exception as e:
        print(f"Error loading salary data: {e}")
        return {'total_salary_expense': 0, 'employee_count': 0, 'message': 'Error loading payroll data'}


def auto_create_monthly_it_expenses():
    """Auto-create monthly IT expenses if not already created for current month"""
    try:
        from datetime import date
        
        current_month = date.today().strftime('%Y-%m')
        
        # Check if IT expenses already exist for this month
        all_expenses = income_expense_store.get_all_expense_records()
        it_expenses_this_month = [
            record for record in all_expenses 
            if record.get('category') == 'IT Services' and record.get('date', '').startswith(current_month)
        ]
        
        if it_expenses_this_month:
            return  # Already created for this month
        
        # Create standard monthly IT expenses
        monthly_it_expenses = [
            {
                'date': f'{current_month}-01',
                'description': 'Monthly Internet Service - Ethio Telecom Business Package',
                'category': 'IT Services',
                'supplier_name': 'Ethio Telecom',
                'supplier_tin': 'TIN_ETHIOTELECOM',
                'gross_amount': 3500.0,
                'tax_rate': 0.15,
                'tax_amount': 525.0,
                'net_amount': 2975.0,
                'payment_method': 'Bank Transfer',
                'receipt_number': f'INET-{current_month}',
                'is_deductible': True
            },
            {
                'date': f'{current_month}-01',
                'description': 'Monthly Software Licenses - Microsoft Office & Accounting Software',
                'category': 'IT Services',
                'supplier_name': 'Software Solutions Ethiopia',
                'supplier_tin': 'TIN_SOFTETH',
                'gross_amount': 2800.0,
                'tax_rate': 0.15,
                'tax_amount': 420.0,
                'net_amount': 2380.0,
                'payment_method': 'Bank Transfer',
                'receipt_number': f'SOFT-{current_month}',
                'is_deductible': True
            },
            {
                'date': f'{current_month}-15',
                'description': 'IT Support & Maintenance Services',
                'category': 'IT Services',
                'supplier_name': 'Addis IT Solutions',
                'supplier_tin': 'TIN_ADDISIT',
                'gross_amount': 4200.0,
                'tax_rate': 0.15,
                'tax_amount': 630.0,
                'net_amount': 3570.0,
                'payment_method': 'Cash',
                'receipt_number': f'ITSUP-{current_month}',
                'is_deductible': True
            }
        ]
        
        # Save each IT expense
        for expense in monthly_it_expenses:
            income_expense_store.save_expense_record(expense)
        
        print(f"✓ Auto-created {len(monthly_it_expenses)} IT expenses for {current_month}")
        
    except Exception as e:
        print(f"Error creating monthly IT expenses: {e}")


@income_expense_bp.route('/')
def dashboard():
    """Income & Expense Management Dashboard with Salary Integration"""
    # Get summary statistics
    stats = income_expense_store.get_summary_statistics()
    
    # Get recent records (last 10)
    recent_income = income_expense_store.get_all_income_records()[-10:]
    recent_expenses = income_expense_store.get_all_expense_records()[-10:]
    
    # Sort by created_at descending
    recent_income = sorted(recent_income, key=lambda x: x.get('created_at', ''), reverse=True)[:10]
    recent_expenses = sorted(recent_expenses, key=lambda x: x.get('created_at', ''), reverse=True)[:10]
    
    # Get payroll/salary data for current month
    salary_data = get_current_month_salary_data()
    
    # Auto-create monthly IT expenses if needed
    auto_create_monthly_it_expenses()

    # Date range for the slider
    date_range = income_expense_store.get_date_range()
    
    return render_template('income_expense/dashboard.html',
                         stats=stats,
                         recent_income=recent_income,
                         recent_expenses=recent_expenses,
                         salary_data=salary_data,
                         date_range=date_range)


# Income Management Routes
@income_expense_bp.route('/income')
def income_list():
    """List all income records"""
    records = income_expense_store.get_all_income_records()
    # Sort by date descending
    records = sorted(records, key=lambda x: x.get('date', ''), reverse=True)
    
    return render_template('income_expense/income_list.html', records=records)


@income_expense_bp.route('/income/add', methods=['GET', 'POST'])
def add_income():
    """Add new income record"""
    if request.method == 'POST':
        try:
            # Get form data
            form_data = request.form.to_dict()
            
            # Calculate tax amount and net amount
            gross_amount = float(form_data.get('gross_amount', 0))
            tax_rate = float(form_data.get('tax_rate', 0)) / 100  # Convert percentage to decimal
            tax_amount = gross_amount * tax_rate
            net_amount = gross_amount - tax_amount
            
            # Prepare income data
            income_data = {
                'date': form_data.get('date'),
                'description': form_data.get('description'),
                'category': form_data.get('category'),
                'client_name': form_data.get('client_name', ''),
                'client_tin': form_data.get('client_tin', ''),
                'gross_amount': gross_amount,
                'tax_rate': tax_rate,
                'tax_amount': tax_amount,
                'net_amount': net_amount,
                'payment_method': form_data.get('payment_method', 'Cash'),
                'reference_number': form_data.get('reference_number', '')
            }
            
            # Save record
            if income_expense_store.save_income_record(income_data):
                flash('Income record added successfully!', 'success')
                return redirect(url_for('income_expense.income_list'))
            else:
                flash('Failed to save income record. Please try again.', 'error')
                
        except ValueError as e:
            flash(f'Invalid input: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error adding income record: {str(e)}', 'error')
    
    # Income categories
    categories = [
        'Product Sales', 'Services', 'Consulting', 'Rental Income',
        'Investment Income', 'Commission', 'Royalties', 'Other'
    ]
    
    # Payment methods
    payment_methods = ['Cash', 'Bank Transfer', 'Check', 'Credit Card', 'Mobile Payment', 'Government Payment']
    
    return render_template('income_expense/add_income.html', 
                         categories=categories, 
                         payment_methods=payment_methods,
                         date=date)


@income_expense_bp.route('/income/view/<record_id>')
def view_income(record_id):
    """View income record details"""
    record = income_expense_store.get_income_record_by_id(record_id)
    if not record:
        flash('Income record not found.', 'error')
        return redirect(url_for('income_expense.income_list'))
    
    return render_template('income_expense/view_income.html', record=record)


@income_expense_bp.route('/income/delete/<record_id>')
def delete_income(record_id):
    """Delete income record"""
    if income_expense_store.delete_income_record(record_id):
        flash('Income record deleted successfully!', 'success')
    else:
        flash('Failed to delete income record.', 'error')
    
    return redirect(url_for('income_expense.income_list'))


# Expense Management Routes
@income_expense_bp.route('/expenses')
def expense_list():
    """List all expense records"""
    records = income_expense_store.get_all_expense_records()
    # Sort by date descending
    records = sorted(records, key=lambda x: x.get('date', ''), reverse=True)
    
    return render_template('income_expense/expense_list.html', records=records)


@income_expense_bp.route('/expenses/add', methods=['GET', 'POST'])
def add_expense():
    """Add new expense record"""
    if request.method == 'POST':
        try:
            # Get form data
            form_data = request.form.to_dict()
            
            # Calculate tax amount and net amount
            gross_amount = float(form_data.get('gross_amount', 0))
            tax_rate = float(form_data.get('tax_rate', 0)) / 100  # Convert percentage to decimal
            tax_amount = gross_amount * tax_rate
            net_amount = gross_amount - tax_amount
            
            # Prepare expense data
            expense_data = {
                'date': form_data.get('date'),
                'description': form_data.get('description'),
                'category': form_data.get('category'),
                'supplier_name': form_data.get('supplier_name', ''),
                'supplier_tin': form_data.get('supplier_tin', ''),
                'gross_amount': gross_amount,
                'tax_rate': tax_rate,
                'tax_amount': tax_amount,
                'net_amount': net_amount,
                'payment_method': form_data.get('payment_method', 'Cash'),
                'receipt_number': form_data.get('receipt_number', ''),
                'is_deductible': 'is_deductible' in form_data
            }
            
            # Save record
            if income_expense_store.save_expense_record(expense_data):
                flash('Expense record added successfully!', 'success')
                return redirect(url_for('income_expense.expense_list'))
            else:
                flash('Failed to save expense record. Please try again.', 'error')
                
        except ValueError as e:
            flash(f'Invalid input: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error adding expense record: {str(e)}', 'error')
    
    # Expense categories
    categories = [
        'Office Expenses', 'Equipment', 'Utilities', 'Marketing',
        'Travel & Transport', 'Professional Services', 'Insurance',
        'Maintenance', 'Supplies', 'Training', 'IT Services', 'Other'
    ]
    
    # Payment methods
    payment_methods = ['Cash', 'Bank Transfer', 'Check', 'Credit Card', 'Mobile Payment']
    
    return render_template('income_expense/add_expense.html', 
                         categories=categories, 
                         payment_methods=payment_methods,
                         date=date)


@income_expense_bp.route('/expenses/view/<record_id>')
def view_expense(record_id):
    """View expense record details"""
    record = income_expense_store.get_expense_record_by_id(record_id)
    if not record:
        flash('Expense record not found.', 'error')
        return redirect(url_for('income_expense.expense_list'))
    
    return render_template('income_expense/view_expense.html', record=record)


@income_expense_bp.route('/expenses/delete/<record_id>')
def delete_expense(record_id):
    """Delete expense record"""
    if income_expense_store.delete_expense_record(record_id):
        flash('Expense record deleted successfully!', 'success')
    else:
        flash('Failed to delete expense record.', 'error')
    
    return redirect(url_for('income_expense.expense_list'))


# Reports
@income_expense_bp.route('/reports')
def reports():
    """Income & Expense Reports with timeframe filtering"""
    from datetime import datetime, timedelta
    
    # Get filter parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    period = request.args.get('period', 'all')  # all, month, quarter, year
    
    # Set default date range based on period
    today = date.today()
    if period == 'month':
        start_date = date(today.year, today.month, 1).isoformat()
        if today.month == 12:
            end_date = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(today.year, today.month + 1, 1) - timedelta(days=1)
        end_date = end_date.isoformat()
    elif period == 'quarter':
        quarter_start_month = ((today.month - 1) // 3) * 3 + 1
        start_date = date(today.year, quarter_start_month, 1).isoformat()
        quarter_end_month = quarter_start_month + 2
        if quarter_end_month == 12:
            end_date = date(today.year, 12, 31).isoformat()
        else:
            end_date = date(today.year, quarter_end_month + 1, 1) - timedelta(days=1)
            end_date = end_date.isoformat()
    elif period == 'year':
        start_date = date(today.year, 1, 1).isoformat()
        end_date = date(today.year, 12, 31).isoformat()
    
    # Get all records
    all_income_records = income_expense_store.get_all_income_records()
    all_expense_records = income_expense_store.get_all_expense_records()
    
    # Filter records by date range if specified
    income_records = all_income_records
    expense_records = all_expense_records
    
    if start_date and end_date:
        income_records = [r for r in income_records if start_date <= r.get('date', '') <= end_date]
        expense_records = [r for r in expense_records if start_date <= r.get('date', '') <= end_date]
    
    # Calculate filtered statistics
    total_income = sum(record.get('net_amount', 0) for record in income_records)
    total_expenses = sum(record.get('net_amount', 0) for record in expense_records)
    total_income_tax = sum(record.get('tax_amount', 0) for record in income_records)
    total_expense_tax = sum(record.get('tax_amount', 0) for record in expense_records)
    
    filtered_stats = {
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net_profit': total_income - total_expenses,
        'income_count': len(income_records),
        'expense_count': len(expense_records),
        'total_income_tax': total_income_tax,
        'total_expense_tax': total_expense_tax
    }
    
    # Group by category
    income_by_category = {}
    for record in income_records:
        category = record.get('category', 'Other')
        income_by_category[category] = income_by_category.get(category, 0) + record.get('net_amount', 0)
    
    expense_by_category = {}
    for record in expense_records:
        category = record.get('category', 'Other')
        expense_by_category[category] = expense_by_category.get(category, 0) + record.get('net_amount', 0)
    
    # Group by month for trend analysis
    income_by_month = {}
    expense_by_month = {}
    
    for record in income_records:
        month_key = record.get('date', '')[:7]  # YYYY-MM format
        income_by_month[month_key] = income_by_month.get(month_key, 0) + record.get('net_amount', 0)
    
    for record in expense_records:
        month_key = record.get('date', '')[:7]  # YYYY-MM format
        expense_by_month[month_key] = expense_by_month.get(month_key, 0) + record.get('net_amount', 0)
    
    return render_template('income_expense/reports.html',
                         stats=filtered_stats,
                         income_by_category=income_by_category,
                         expense_by_category=expense_by_category,
                         income_by_month=income_by_month,
                         expense_by_month=expense_by_month,
                         start_date=start_date,
                         end_date=end_date,
                         period=period,
                         record_count={'income': len(income_records), 'expense': len(expense_records)})


# Excel Import/Export Routes
@income_expense_bp.route('/export/excel')
def export_excel():
    """Export income and expense data to Excel"""
    try:
        file_path = income_expense_store.export_to_excel()
        if file_path:
            # Generate filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'income_expense_export_{timestamp}.xlsx'
            
            # Send file as download
            response = make_response(send_file(file_path, as_attachment=True, download_name=filename))
            
            # Clean up temporary file after sending
            @response.call_on_close
            def remove_file():
                try:
                    os.unlink(file_path)
                except OSError:
                    pass
            
            return response
        else:
            flash('Failed to export data to Excel.', 'error')
            return redirect(url_for('income_expense.dashboard'))
            
    except Exception as e:
        flash(f'Export error: {str(e)}', 'error')
        return redirect(url_for('income_expense.dashboard'))


@income_expense_bp.route('/import/excel', methods=['GET', 'POST'])
def import_excel():
    """Import income and expense data from Excel"""
    if request.method == 'POST':
        try:
            # Check if file was uploaded
            if 'excel_file' not in request.files:
                flash('No file selected.', 'error')
                return redirect(request.url)
            
            file = request.files['excel_file']
            if file.filename == '':
                flash('No file selected.', 'error')
                return redirect(request.url)
            
            if file and file.filename.endswith(('.xlsx', '.xls')):
                # Save uploaded file temporarily
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
                file.save(temp_file.name)
                temp_file.close()
                
                # Import data
                result = income_expense_store.import_from_excel(temp_file.name)
                
                # Clean up temporary file
                os.unlink(temp_file.name)
                
                # SIEM: Log upload event
                try:
                    from siem_data_store import siem_store
                    siem_store.log_upload_event(
                        request, module='income_expense', endpoint='/income-expense/import/excel',
                        filename=file.filename,
                        records_imported=result.get('imported_count', 0),
                        status='success' if result['success'] else 'failed',
                        details=result.get('message', '')
                    )
                except Exception as e:
                    logger.warning("SIEM logging failed: %s", e)
                
                # Show results
                if result['success']:
                    flash(f"Import successful! {result['message']}", 'success')
                    if result['errors']:
                        flash(f"Some rows had errors: {'; '.join(result['errors'][:5])}", 'warning')
                else:
                    flash(f"Import failed: {result['message']}", 'error')
                
                return redirect(url_for('income_expense.dashboard'))
            else:
                flash('Please upload a valid Excel file (.xlsx or .xls).', 'error')
                
        except Exception as e:
            # SIEM: Log exception
            try:
                from siem_data_store import siem_store
                siem_store.log_upload_event(
                    request, module='income_expense', endpoint='/income-expense/import/excel',
                    filename=file.filename if 'file' in dir() else '',
                    status='failed', details=str(e)
                )
            except Exception as e2:
                logger.warning("SIEM logging failed: %s", e2)
            flash(f'Import error: {str(e)}', 'error')
    
    return render_template('income_expense/import_excel.html')


@income_expense_bp.route('/download/sample')
def download_sample():
    """Download sample Excel file"""
    try:
        file_path = income_expense_store.create_sample_excel_file()
        if file_path:
            filename = 'income_expense_sample_data.xlsx'
            return send_file(file_path, as_attachment=True, download_name=filename)
        else:
            flash('Failed to create sample file.', 'error')
            return redirect(url_for('income_expense.dashboard'))
            
    except Exception as e:
        flash(f'Error creating sample file: {str(e)}', 'error')
        return redirect(url_for('income_expense.dashboard'))


# API Endpoints
@income_expense_bp.route('/api/stats')
def api_stats():
    """Get income and expense statistics as JSON – supports ?from=YYYY-MM-DD&to=YYYY-MM-DD"""
    try:
        date_from = request.args.get('from')
        date_to = request.args.get('to')
        stats = income_expense_store.get_summary_statistics(date_from=date_from, date_to=date_to)
        salary_data = get_current_month_salary_data()
        stats['salary_expense'] = salary_data['total_salary_expense']
        stats['employee_count'] = salary_data['employee_count']
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@income_expense_bp.route('/api/income')
def api_income():
    """Get all income records as JSON"""
    try:
        records = income_expense_store.get_all_income_records()
        return jsonify(records)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@income_expense_bp.route('/api/expenses')
def api_expenses():
    """Get all expense records as JSON"""
    try:
        records = income_expense_store.get_all_expense_records()
        return jsonify(records)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@income_expense_bp.route('/create-monthly-it-expenses', methods=['POST'])
def create_monthly_it_expenses():
    """Manually trigger creation of monthly IT expenses"""
    try:
        auto_create_monthly_it_expenses()
        flash('Monthly IT expenses created successfully!', 'success')
    except Exception as e:
        flash(f'Error creating IT expenses: {str(e)}', 'error')
    
    return redirect(url_for('income_expense.dashboard'))


@income_expense_bp.route('/api/create-it-expenses', methods=['POST'])
def api_create_it_expenses():
    """API endpoint to create monthly IT expenses"""
    try:
        auto_create_monthly_it_expenses()
        return jsonify({'success': True, 'message': 'Monthly IT expenses created successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500