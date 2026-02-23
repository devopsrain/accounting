"""
Chart of Accounts Routes

Flask routes for chart of accounts management with Excel import/export functionality
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file
from datetime import datetime, date
import logging
import tempfile
import os

from chart_of_accounts_data_store import ChartOfAccountsDataStore

logger = logging.getLogger(__name__)

# Create blueprint
accounts_bp = Blueprint('accounts', __name__, url_prefix='/accounts')

# Create data store
accounts_store = ChartOfAccountsDataStore()


@accounts_bp.route('/')
def accounts_list():
    """List chart of accounts"""
    company_id = request.args.get('company_id', 'default')
    account_type = request.args.get('account_type')
    
    # Get all accounts
    accounts_df = accounts_store.read_all_accounts(company_id)
    
    # Filter by account type if specified
    if account_type and not accounts_df.empty:
        accounts_df = accounts_df[accounts_df['account_type'] == account_type]
    
    # Group by account type for display
    accounts_by_type = {}
    if not accounts_df.empty:
        for account_type_name in accounts_df['account_type'].unique():
            type_accounts = accounts_df[accounts_df['account_type'] == account_type_name]
            accounts_by_type[account_type_name] = type_accounts.to_dict('records')
    
    # Calculate totals by type
    type_totals = {}
    for acc_type, accounts in accounts_by_type.items():
        type_totals[acc_type] = sum(acc['current_balance'] for acc in accounts)
    
    return render_template('accounts/list.html',
                         accounts_by_type=accounts_by_type,
                         type_totals=type_totals,
                         total_accounts=len(accounts_df),
                         filters={'company_id': company_id, 'account_type': account_type})


@accounts_bp.route('/view/<account_code>')
def view_account(account_code):
    """View account details"""
    company_id = request.args.get('company_id', 'default')
    
    account = accounts_store.get_account_by_code(account_code, company_id)
    
    if not account:
        flash('Account not found', 'error')
        return redirect(url_for('accounts.accounts_list'))
    
    return render_template('accounts/view.html', account=account)


@accounts_bp.route('/add', methods=['GET', 'POST'])
def add_account():
    """Add new account"""
    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form
            
            account_data = {
                'account_code': data.get('account_code'),
                'account_name': data.get('account_name'),
                'account_type': data.get('account_type'),
                'account_subtype': data.get('account_subtype', ''),
                'parent_account': data.get('parent_account', ''),
                'description': data.get('description', ''),
                'normal_balance': data.get('normal_balance', 'Debit'),
                'current_balance': float(data.get('current_balance', 0)),
                'company_id': data.get('company_id', 'default'),
                'is_active': True
            }
            
            if accounts_store.save_account(account_data):
                if request.is_json:
                    return jsonify({'success': True, 'account_code': account_data['account_code']})
                
                flash('Account added successfully!', 'success')
                return redirect(url_for('accounts.view_account', account_code=account_data['account_code']))
            else:
                if request.is_json:
                    return jsonify({'success': False, 'error': 'Failed to save account'}), 400
                flash('Failed to save account', 'error')
                
        except Exception as e:
            if request.is_json:
                return jsonify({'success': False, 'error': str(e)}), 400
            flash(f'Error adding account: {str(e)}', 'error')
    
    return render_template('accounts/add.html')


@accounts_bp.route('/edit/<account_code>', methods=['GET', 'POST'])
def edit_account(account_code):
    """Edit existing account"""
    company_id = request.args.get('company_id', 'default')
    
    account = accounts_store.get_account_by_code(account_code, company_id)
    
    if not account:
        flash('Account not found', 'error')
        return redirect(url_for('accounts.accounts_list'))
    
    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form
            
            # Update account data (preserve existing values for fields not provided)
            account.update({
                'account_name': data.get('account_name', account['account_name']),
                'account_type': data.get('account_type', account['account_type']),
                'account_subtype': data.get('account_subtype', account['account_subtype']),
                'parent_account': data.get('parent_account', account['parent_account']),
                'description': data.get('description', account['description']),
                'normal_balance': data.get('normal_balance', account['normal_balance']),
                'current_balance': float(data.get('current_balance', account['current_balance'])),
                'is_active': data.get('is_active', account['is_active'])
            })
            
            if accounts_store.save_account(account):
                if request.is_json:
                    return jsonify({'success': True})
                
                flash('Account updated successfully!', 'success')
                return redirect(url_for('accounts.view_account', account_code=account_code))
            else:
                if request.is_json:
                    return jsonify({'success': False, 'error': 'Failed to update account'}), 400
                flash('Failed to update account', 'error')
                
        except Exception as e:
            if request.is_json:
                return jsonify({'success': False, 'error': str(e)}), 400
            flash(f'Error updating account: {str(e)}', 'error')
    
    return render_template('accounts/edit.html', account=account)


# Excel Import/Export Routes
@accounts_bp.route('/export/excel')
def export_excel():
    """Export chart of accounts to Excel"""
    company_id = request.args.get('company_id')
    
    try:
        filepath = accounts_store.export_to_excel(company_id)
        filename = f'chart_of_accounts_{datetime.now().strftime("%Y%m%d")}.xlsx'
        return send_file(filepath, as_attachment=True, download_name=filename)
        
    except Exception as e:
        flash(f'Export failed: {str(e)}', 'error')
        return redirect(url_for('accounts.accounts_list'))


@accounts_bp.route('/import/excel', methods=['GET', 'POST'])
def import_excel():
    """Import chart of accounts from Excel"""
    if request.method == 'POST':
        if 'excel_file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        
        file = request.files['excel_file']
        company_id = request.form.get('company_id', 'default')
        
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        if file and file.filename.lower().endswith(('.xlsx', '.xls')):
            try:
                # Save uploaded file temporarily
                with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
                    file.save(tmp_file.name)
                    
                    # Import from Excel
                    result = accounts_store.import_from_excel(tmp_file.name, company_id)
                    
                    # Clean up temp file
                    os.unlink(tmp_file.name)
                
                if result['success']:
                    # SIEM: Log successful upload
                    try:
                        from siem_data_store import siem_store
                        siem_store.log_upload_event(
                            request, module='accounts', endpoint='/accounts/import/excel',
                            filename=file.filename, records_imported=result.get('imported_count', 0),
                            status='success', details=f"Imported {result.get('imported_count', 0)} accounts"
                        )
                    except Exception as e:
                        logger.warning("SIEM logging failed: %s", e)
                    flash(f"Successfully imported {result['imported_count']} accounts!", 'success')
                    if result['errors']:
                        for error in result['errors'][:3]:
                            flash(f"Warning: {error}", 'warning')
                else:
                    # SIEM: Log failed upload
                    try:
                        from siem_data_store import siem_store
                        siem_store.log_upload_event(
                            request, module='accounts', endpoint='/accounts/import/excel',
                            filename=file.filename, status='failed',
                            details='; '.join(result.get('errors', [])[:3])
                        )
                    except Exception as e:
                        logger.warning("SIEM logging failed: %s", e)
                    flash('Import failed. Please check your file format.', 'error')
                    for error in result['errors'][:3]:
                        flash(f"Error: {error}", 'error')
                        
            except Exception as e:
                # SIEM: Log exception
                try:
                    from siem_data_store import siem_store
                    siem_store.log_upload_event(
                        request, module='accounts', endpoint='/accounts/import/excel',
                        filename=file.filename if 'file' in dir() else '',
                        status='failed', details=str(e)
                    )
                except Exception as e2:
                    logger.warning("SIEM logging failed: %s", e2)
                flash(f'Import failed: {str(e)}', 'error')
        else:
            flash('Please upload a valid Excel file (.xlsx or .xls)', 'error')
        
        return redirect(url_for('accounts.accounts_list'))
    
    # GET request - show import form
    return render_template('accounts/import_excel.html')


@accounts_bp.route('/download/sample')
def download_sample():
    """Download sample chart of accounts Excel file"""
    try:
        filepath = accounts_store.create_sample_excel_file()
        return send_file(filepath, as_attachment=True, download_name='chart_of_accounts_sample_data.xlsx')
        
    except Exception as e:
        flash(f'Sample download failed: {str(e)}', 'error')
        return redirect(url_for('accounts.accounts_list'))


@accounts_bp.route('/dashboard')
def dashboard():
    """Chart of accounts dashboard"""
    company_id = request.args.get('company_id', 'default')
    
    # Get all accounts
    accounts_df = accounts_store.read_all_accounts(company_id)
    
    # Calculate statistics
    stats = {
        'total_accounts': len(accounts_df),
        'active_accounts': len(accounts_df[accounts_df['is_active']]) if not accounts_df.empty else 0,
        'asset_accounts': len(accounts_df[accounts_df['account_type'] == 'Asset']) if not accounts_df.empty else 0,
        'liability_accounts': len(accounts_df[accounts_df['account_type'] == 'Liability']) if not accounts_df.empty else 0,
        'equity_accounts': len(accounts_df[accounts_df['account_type'] == 'Equity']) if not accounts_df.empty else 0,
        'revenue_accounts': len(accounts_df[accounts_df['account_type'] == 'Revenue']) if not accounts_df.empty else 0,
        'expense_accounts': len(accounts_df[accounts_df['account_type'] == 'Expense']) if not accounts_df.empty else 0,
    }
    
    # Calculate balances by type
    balance_summary = {}
    if not accounts_df.empty:
        for account_type in ['Asset', 'Liability', 'Equity', 'Revenue', 'Expense']:
            type_accounts = accounts_df[accounts_df['account_type'] == account_type]
            balance_summary[account_type] = type_accounts['current_balance'].sum() if not type_accounts.empty else 0
    
    # Recent accounts (last 10 created)
    recent_accounts = []
    if not accounts_df.empty:
        sorted_accounts = accounts_df.sort_values('created_date', ascending=False)
        recent_accounts = sorted_accounts.head(10).to_dict('records')
    
    return render_template('accounts/dashboard.html',
                         stats=stats,
                         balance_summary=balance_summary,
                         recent_accounts=recent_accounts,
                         company_id=company_id)


@accounts_bp.route('/trial-balance')
def trial_balance():
    """Generate trial balance report"""
    company_id = request.args.get('company_id', 'default')
    
    # Get all active accounts
    accounts_df = accounts_store.read_all_accounts(company_id)
    
    if accounts_df.empty:
        flash('No accounts found', 'warning')
        return render_template('accounts/trial_balance.html', accounts=[], totals={'debit': 0, 'credit': 0})
    
    # Filter active accounts with non-zero balances
    active_accounts = accounts_df[accounts_df['is_active'] & (accounts_df['current_balance'] != 0)]
    
    # Separate debit and credit balances based on normal balance
    trial_balance_accounts = []
    total_debits = 0
    total_credits = 0
    
    for _, account in active_accounts.iterrows():
        balance = account['current_balance']
        
        if account['normal_balance'] == 'Debit':
            debit_amount = balance if balance > 0 else 0
            credit_amount = abs(balance) if balance < 0 else 0
        else:  # Credit
            credit_amount = balance if balance > 0 else 0
            debit_amount = abs(balance) if balance < 0 else 0
        
        if debit_amount != 0 or credit_amount != 0:
            trial_balance_accounts.append({
                'account_code': account['account_code'],
                'account_name': account['account_name'],
                'debit_amount': debit_amount,
                'credit_amount': credit_amount
            })
            
            total_debits += debit_amount
            total_credits += credit_amount
    
    totals = {
        'debit': total_debits,
        'credit': total_credits,
        'balanced': abs(total_debits - total_credits) < 0.01
    }
    
    return render_template('accounts/trial_balance.html',
                         accounts=trial_balance_accounts,
                         totals=totals,
                         company_id=company_id)