"""
VAT Portal Routes

Flask routes for VAT context portal with income, expense, and summary functionality
"""

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash, send_file
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
import logging
import uuid

logger = logging.getLogger(__name__)

from models.vat_portal import (
    VATContextManager, VATType, IncomeCategory, ExpenseCategory, TransactionType,
    IncomeRecord, ExpenseRecord, CapitalRecord, FinancialSummary
)
from vat_data_store import VATDataStore
from auth_data_store import login_required

# Create VAT portal manager (in production, this would be database-backed)
vat_manager = VATContextManager()

# Create VAT data store for Excel functionality
vat_data_store = VATDataStore()

# Create blueprint
vat_bp = Blueprint('vat', __name__, url_prefix='/vat')

def get_current_company():
    """Get current company ID from session."""
    return session.get('current_company_id', 'demo_company')

# Dashboard and main pages
@vat_bp.route('/dashboard')
@login_required
def dashboard():
    """VAT Portal Dashboard"""
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('multicompany.select_company'))
    
    # Get company statistics
    stats = vat_manager.get_company_statistics(company_id)
    
    # Get recent transactions (last 10)
    recent_income = vat_manager.get_company_income_records(company_id)[-10:]
    recent_expenses = vat_manager.get_company_expense_records(company_id)[-10:]
    
    # Get current month summary
    today = date.today()
    month_start = date(today.year, today.month, 1)
    month_end = date(today.year, today.month + 1, 1) - timedelta(days=1) if today.month < 12 else date(today.year, 12, 31)
    
    monthly_summary = vat_manager.generate_financial_summary(company_id, month_start, month_end)
    
    return render_template('vat/dashboard.html',
                         stats=stats,
                         recent_income=recent_income,
                         recent_expenses=recent_expenses,
                         monthly_summary=monthly_summary)

# Income Management
@vat_bp.route('/income')
@login_required
def income_list():
    """Income records list"""
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('multicompany.select_company'))
    
    # Get filter parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    category = request.args.get('category')
    
    # Convert date strings to date objects
    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None
    
    # Get income records
    income_records = vat_manager.get_company_income_records(company_id, start_date_obj, end_date_obj)
    
    # Filter by category if specified
    if category:
        income_records = [r for r in income_records if r.category.value == category]
    
    # Calculate totals
    total_gross = sum(record.gross_amount for record in income_records)
    total_vat = sum(record.vat_amount for record in income_records)
    total_net = sum(record.net_amount for record in income_records)
    totals = {'gross_amount': total_gross, 'vat_amount': total_vat, 'net_amount': total_net}
    
    return render_template('vat/income_list.html',
                         income_transactions=income_records,
                         income_records=income_records,
                         total_gross=total_gross,
                         total_vat=total_vat,
                         total_net=total_net,
                         totals=totals,
                         income_categories=IncomeCategory,
                         vat_types=VATType,
                         filters={'start_date': start_date, 'end_date': end_date, 'category': category})

@vat_bp.route('/income/add', methods=['GET', 'POST'])
@login_required
def add_income():
    """Add new income record"""
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('multicompany.select_company'))
    
    if request.method == 'POST':
        data = request.get_json()
        
        try:
            # Convert and validate data
            income_data = {
                'contract_date': datetime.strptime(data.get('contract_date'), '%Y-%m-%d').date(),
                'description': data.get('description'),
                'category': IncomeCategory(data.get('category')),
                'gross_amount': Decimal(str(data.get('gross_amount', 0))),
                'vat_type': VATType(data.get('vat_type')),
                'vat_rate': Decimal(str(data.get('vat_rate', 0.15))),
                'customer_name': data.get('customer_name', ''),
                'customer_tin': data.get('customer_tin', ''),
                'invoice_number': data.get('invoice_number', ''),
                'created_by': session.get('username', '')
            }
            
            income_record = vat_manager.add_income_record(company_id, income_data)
            
            return jsonify({
                'success': True,
                'income_id': income_record.income_id,
                'message': 'Income record added successfully'
            })
        
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 400
    
    # GET request - show form
    vat_configs = vat_manager.get_vat_configurations()
    return render_template('vat/add_income.html',
                         income_categories=IncomeCategory,
                         vat_types=VATType,
                         vat_configs=vat_configs)

# Expense Management  
@vat_bp.route('/expenses')
@login_required
def expense_list():
    """Expense records list"""
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('multicompany.select_company'))
    
    # Get filter parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    category = request.args.get('category')
    
    # Convert date strings to date objects
    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None
    
    # Get expense records
    expense_records = vat_manager.get_company_expense_records(company_id, start_date_obj, end_date_obj)
    
    # Filter by category if specified
    if category:
        expense_records = [r for r in expense_records if r.category.value == category]
    
    # Calculate totals
    total_gross = sum(record.gross_amount for record in expense_records)
    total_vat = sum(record.vat_amount for record in expense_records)
    total_net = sum(record.net_amount for record in expense_records)
    totals = {'gross_amount': total_gross, 'vat_amount': total_vat, 'net_amount': total_net}
    
    return render_template('vat/expense_list.html',
                         expense_transactions=expense_records,
                         expense_records=expense_records,
                         total_gross=total_gross,
                         total_vat=total_vat,
                         total_net=total_net,
                         totals=totals,
                         expense_categories=ExpenseCategory,
                         vat_types=VATType,
                         filters={'start_date': start_date, 'end_date': end_date, 'category': category})

@vat_bp.route('/expenses/add', methods=['GET', 'POST'])
@login_required
def add_expense():
    """Add new expense record"""
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('multicompany.select_company'))
    
    if request.method == 'POST':
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        try:
            # Convert and validate data
            expense_data = {
                'expense_date': datetime.strptime(data.get('expense_date'), '%Y-%m-%d').date(),
                'description': data.get('description'),
                'category': ExpenseCategory(data.get('category')),
                'gross_amount': Decimal(str(data.get('gross_amount', 0))),
                'vat_type': VATType(data.get('vat_type')),
                'vat_rate': Decimal(str(data.get('vat_rate', 0.15))),
                'supplier_name': data.get('supplier_name', ''),
                'supplier_tin': data.get('supplier_tin', ''),
                'receipt_number': data.get('receipt_number', ''),
                'created_by': session.get('username', '')
            }
            
            expense_record = vat_manager.add_expense_record(company_id, expense_data)
            
            # Handle response based on request type
            if request.is_json:
                return jsonify({
                    'success': True,
                    'expense_id': expense_record.expense_id,
                    'message': 'Expense record added successfully'
                })
            else:
                flash('Expense record added successfully!')
                return redirect(url_for('vat.expense_list'))
        
        except Exception as e:
            if request.is_json:
                return jsonify({'success': False, 'error': str(e)}), 400
            else:
                flash(f'Error adding expense: {str(e)}')
                return redirect(url_for('vat.add_expense'))
    
    # GET request - show form
    vat_configs = vat_manager.get_vat_configurations()
    return render_template('vat/add_expense.html',
                         expense_categories=ExpenseCategory,
                         vat_types=VATType,
                         vat_configs=vat_configs)

# Capital Management
@vat_bp.route('/capital')
@login_required
def capital_list():
    """Capital records list"""
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('multicompany.select_company'))
    
    # Get capital records
    capital_records = vat_manager.get_company_capital_records(company_id)
    
    # Calculate totals for template
    injections = [r for r in capital_records if getattr(r, 'transaction_type', '') == 'INJECTION']
    withdrawals = [r for r in capital_records if getattr(r, 'transaction_type', '') != 'INJECTION']
    total_injected = sum(r.amount for r in injections)
    total_withdrawn = sum(r.amount for r in withdrawals)
    total_vat = sum(getattr(r, 'vat_amount', 0) for r in capital_records)
    total_capital = sum(record.amount for record in capital_records)
    net_capital = total_injected - total_withdrawn
    
    return render_template('vat/capital_list.html',
                         capital_transactions=capital_records,
                         capital_records=capital_records,
                         injections_count=len(injections),
                         withdrawals_count=len(withdrawals),
                         total_injected=total_injected,
                         total_withdrawn=total_withdrawn,
                         total_vat=total_vat,
                         net_capital=net_capital,
                         total_capital=total_capital)

@vat_bp.route('/capital/add', methods=['GET', 'POST'])
@login_required
def add_capital():
    """Add new capital record"""
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('multicompany.select_company'))
    
    if request.method == 'POST':
        data = request.get_json()
        
        try:
            # Convert and validate data
            capital_data = {
                'transaction_date': datetime.strptime(data.get('transaction_date'), '%Y-%m-%d').date(),
                'description': data.get('description'),
                'capital_type': data.get('capital_type'),
                'amount': Decimal(str(data.get('amount', 0))),
                'source': data.get('source', ''),
                'reference_number': data.get('reference_number', ''),
                'created_by': session.get('username', '')
            }
            
            capital_record = vat_manager.add_capital_record(company_id, capital_data)
            
            return jsonify({
                'success': True,
                'capital_id': capital_record.capital_id,
                'message': 'Capital record added successfully'
            })
        
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 400
    
    return render_template('vat/add_capital.html')

# Summary and Reports
@vat_bp.route('/summary')
@login_required
def financial_summary():
    """Financial summary page"""
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('multicompany.select_company'))
    
    # Get parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # Default to current year if no dates provided
    if not start_date or not end_date:
        today = date.today()
        start_date = f"{today.year}-01-01"
        end_date = f"{today.year}-12-31"
    
    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    # Generate comprehensive summary
    summary = vat_manager.generate_financial_summary(company_id, start_date_obj, end_date_obj)
    
    # Get detailed records for analysis
    income_records = vat_manager.get_company_income_records(company_id, start_date_obj, end_date_obj)
    expense_records = vat_manager.get_company_expense_records(company_id, start_date_obj, end_date_obj)
    capital_records = vat_manager.get_company_capital_records(company_id, start_date_obj, end_date_obj)
    
    return render_template('vat/financial_summary.html',
                         summary=summary,
                         income_records=income_records,
                         expense_records=expense_records,
                         capital_records=capital_records,
                         start_date=start_date,
                         end_date=end_date)

# VAT Configuration
@vat_bp.route('/vat-config')
@login_required
def vat_config():
    """VAT configuration page"""
    vat_configs = vat_manager.get_vat_configurations()
    
    return render_template('vat/vat_config.html',
                         vat_configs=vat_configs,
                         vat_types=VATType)

@vat_bp.route('/vat-config/add', methods=['POST'])
@login_required
def add_vat_config():
    """Add or update VAT configuration"""
    data = request.get_json()
    
    try:
        from models.vat_portal import VATConfiguration
        
        vat_config = VATConfiguration(
            vat_id=data.get('vat_id', str(uuid.uuid4())),
            vat_type=VATType(data.get('vat_type')),
            rate=Decimal(str(data.get('rate', 0))),
            description=data.get('description', ''),
            is_active=data.get('is_active', True)
        )
        
        vat_manager.add_vat_configuration(vat_config)
        
        return jsonify({
            'success': True,
            'message': 'VAT configuration saved successfully'
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

# API endpoints
@vat_bp.route('/api/stats')
@login_required
def api_stats():
    """Get company VAT statistics"""
    company_id = get_current_company()
    if not company_id:
        return jsonify({'error': 'No company selected'}), 400
    
    stats = vat_manager.get_company_statistics(company_id)
    return jsonify(stats)

@vat_bp.route('/api/vat-rate/<vat_type>')
def api_vat_rate(vat_type: str):
    """Get VAT rate for a VAT type"""
    try:
        vat_type_enum = VATType(vat_type)
        vat_configs = vat_manager.get_vat_configurations()
        
        for config in vat_configs.values():
            if config.vat_type == vat_type_enum and config.is_active:
                return jsonify({'rate': float(config.rate)})
        
        return jsonify({'rate': 0.15})  # Default rate
    except:
        return jsonify({'rate': 0.15})  # Default rate


# Excel Import/Export Routes
@vat_bp.route('/export/excel')
@login_required
def export_excel():
    """Export VAT data to Excel"""
    company_id = get_current_company()
    if not company_id:
        flash('No company selected', 'error')
        return redirect(url_for('vat.dashboard'))
    
    try:
        filepath = vat_data_store.export_to_excel(company_id)
        return send_file(filepath, as_attachment=True, download_name=f'vat_export_{company_id}.xlsx')
        
    except Exception as e:
        flash(f'Export failed: {str(e)}', 'error')
        return redirect(url_for('vat.dashboard'))


@vat_bp.route('/import/excel', methods=['GET', 'POST'])
@login_required
def import_excel():
    """Import VAT data from Excel"""
    company_id = get_current_company()
    if not company_id:
        flash('No company selected', 'error')
        return redirect(url_for('vat.dashboard'))
    
    if request.method == 'POST':
        if 'excel_file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        
        file = request.files['excel_file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        if file and file.filename.lower().endswith(('.xlsx', '.xls')):
            try:
                # Save uploaded file temporarily
                import tempfile
                import os
                
                with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
                    file.save(tmp_file.name)
                    tmp_path = tmp_file.name
                
                try:
                    # Import from Excel
                    result = vat_data_store.import_from_excel(tmp_path, company_id)
                finally:
                    # Clean up temp file even if import fails
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                
                # SIEM: Log upload event
                try:
                    from siem_data_store import siem_store
                    total_imported = sum(result.get('imported_counts', {}).values()) if result.get('imported_counts') else 0
                    siem_store.log_upload_event(
                        request, module='vat', endpoint='/vat/import/excel',
                        filename=file.filename,
                        records_imported=total_imported,
                        status='success' if result['success'] else 'failed',
                        details=f"Imported {total_imported} VAT records"
                    )
                except Exception as e:
                    logger.warning("SIEM logging failed: %s", e)
                
                if result['success']:
                    flash(f"Successfully imported {sum(result['imported_counts'].values())} records!", 'success')
                    if result['errors']:
                        for error in result['errors'][:5]:  # Show first 5 errors
                            flash(f"Warning: {error}", 'warning')
                else:
                    flash('Import failed. Please check your file format.', 'error')
                    for error in result['errors'][:5]:
                        flash(f"Error: {error}", 'error')
                        
            except Exception as e:
                # SIEM: Log exception
                try:
                    from siem_data_store import siem_store
                    siem_store.log_upload_event(
                        request, module='vat', endpoint='/vat/import/excel',
                        filename=file.filename if 'file' in dir() else '',
                        status='failed', details=str(e)
                    )
                except Exception as e2:
                    logger.warning("SIEM logging failed: %s", e2)
                flash(f'Import failed: {str(e)}', 'error')
        else:
            flash('Please upload a valid Excel file (.xlsx or .xls)', 'error')
        
        return redirect(url_for('vat.dashboard'))
    
    # GET request - show import form
    return render_template('vat/import_excel.html')


@vat_bp.route('/download/sample')
def download_sample():
    """Download sample VAT Excel file"""
    try:
        filepath = vat_data_store.create_sample_excel_file()
        return send_file(filepath, as_attachment=True, download_name='vat_sample_data.xlsx')
        
    except Exception as e:
        flash(f'Sample download failed: {str(e)}', 'error')
        return redirect(url_for('vat.dashboard'))