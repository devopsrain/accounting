"""
Transaction Management Routes

Flask routes for transaction import, review, flagging and export.
"""

from flask import (
    Blueprint, render_template, request, jsonify, redirect,
    url_for, flash, send_file, make_response
)
from werkzeug.utils import secure_filename
from datetime import datetime
import tempfile
import os
import pandas as pd

from transaction_data_store import TransactionDataStore
from siem_data_store import siem_store

# Create blueprint
transaction_bp = Blueprint('transaction', __name__, url_prefix='/transactions')

# Create data store
transaction_store = TransactionDataStore()


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------
@transaction_bp.route('/')
@transaction_bp.route('/dashboard')
def dashboard():
    """Transaction module dashboard with summary statistics."""
    stats = transaction_store.get_summary_statistics()
    recent_imports = transaction_store.get_import_history()[-5:]
    recent_imports.reverse()  # Most recent first
    flagged_accounts = transaction_store.get_flagged_accounts()

    return render_template(
        'transaction/dashboard.html',
        stats=stats,
        recent_imports=recent_imports,
        flagged_accounts=flagged_accounts,
    )


# ------------------------------------------------------------------
# Import
# ------------------------------------------------------------------
@transaction_bp.route('/import', methods=['GET', 'POST'])
def import_transactions():
    """Import transactions from Excel (same pattern as payroll import)."""
    if request.method == 'POST':
        try:
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

            # Read Excel file directly from stream (like payroll module)
            df = pd.read_excel(file, sheet_name=0)

            if df.empty:
                flash('The Excel file is empty', 'error')
                return redirect(request.url)

            result = transaction_store.import_from_dataframe(df, file.filename)

            # SIEM: Log upload event
            siem_store.log_upload_event(
                request, module='transaction', endpoint='/transactions/import',
                filename=file.filename,
                records_imported=result.get('imported', 0),
                status='success' if result['success'] else 'failed',
                details=result.get('message', '')
            )

            if result['success']:
                flash(result['message'], 'success')
            else:
                flash(result['message'], 'error')

            return render_template(
                'transaction/import_result.html',
                result=result,
                filename=file.filename,
            )

        except Exception as e:
            # SIEM: Log failed upload
            siem_store.log_upload_event(
                request, module='transaction', endpoint='/transactions/import',
                filename=file.filename if 'file' in dir() else '',
                status='failed', details=str(e)
            )
            flash(f'Error importing file: {str(e)}', 'error')
            return redirect(request.url)

    return render_template('transaction/import.html')


@transaction_bp.route('/download-template')
def download_template():
    """Download a sample Excel template for transaction imports."""
    filepath = transaction_store.generate_sample_excel()
    if filepath:
        return send_file(
            filepath,
            as_attachment=True,
            download_name='transaction_import_template.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
    flash('Could not generate template', 'danger')
    return redirect(url_for('transaction.import_transactions'))


# ------------------------------------------------------------------
# Transaction list & detail
# ------------------------------------------------------------------
@transaction_bp.route('/list')
def transaction_list():
    """List all transactions with filtering."""
    transactions = transaction_store.get_all_transactions()

    # Apply filters
    filter_type = request.args.get('filter', 'all')
    search_query = request.args.get('search', '').strip().lower()
    review_filter = request.args.get('review_status', '')

    if filter_type == 'flagged':
        transactions = [t for t in transactions if t.get('is_flagged')]
    elif filter_type == 'individual':
        transactions = [t for t in transactions if t.get('has_individual_name')]

    if review_filter:
        transactions = [t for t in transactions if t.get('review_status') == review_filter]

    if search_query:
        transactions = [
            t for t in transactions
            if search_query in str(t.get('account_name', '')).lower()
            or search_query in str(t.get('account_code', '')).lower()
            or search_query in str(t.get('description', '')).lower()
            or search_query in str(t.get('counterparty', '')).lower()
            or search_query in str(t.get('reference', '')).lower()
        ]

    # Sort by date descending
    transactions.sort(key=lambda x: x.get('date', ''), reverse=True)

    stats = transaction_store.get_summary_statistics()

    return render_template(
        'transaction/transaction_list.html',
        transactions=transactions,
        stats=stats,
        filter_type=filter_type,
        search_query=request.args.get('search', ''),
        review_filter=review_filter,
    )


@transaction_bp.route('/detail/<txn_id>')
def transaction_detail(txn_id):
    """View a single transaction detail."""
    txn = transaction_store.get_transaction_by_id(txn_id)
    if not txn:
        flash('Transaction not found', 'danger')
        return redirect(url_for('transaction.transaction_list'))
    return render_template('transaction/detail.html', transaction=txn)


# ------------------------------------------------------------------
# Review actions
# ------------------------------------------------------------------
@transaction_bp.route('/review/<txn_id>', methods=['POST'])
def review_transaction(txn_id):
    """Update review status for a transaction."""
    status = request.form.get('review_status', 'pending')
    notes = request.form.get('reviewer_notes', '')

    if transaction_store.update_review_status(txn_id, status, notes):
        flash(f'Transaction marked as {status}', 'success')
    else:
        flash('Failed to update review status', 'danger')

    return redirect(request.referrer or url_for('transaction.transaction_list'))


@transaction_bp.route('/delete/<txn_id>', methods=['POST'])
def delete_transaction(txn_id):
    """Delete a transaction."""
    if transaction_store.delete_transaction(txn_id):
        flash('Transaction deleted', 'success')
    else:
        flash('Failed to delete transaction', 'danger')
    return redirect(url_for('transaction.transaction_list'))


# ------------------------------------------------------------------
# Flagged accounts
# ------------------------------------------------------------------
@transaction_bp.route('/flagged-accounts')
def flagged_accounts():
    """List all flagged accounts."""
    accounts = transaction_store.get_flagged_accounts()
    return render_template('transaction/flagged_accounts.html', accounts=accounts)


@transaction_bp.route('/flag-account', methods=['POST'])
def flag_account():
    """Manually flag an account."""
    code = request.form.get('account_code', '').strip()
    name = request.form.get('account_name', '').strip()
    reason = request.form.get('reason', 'Manually flagged').strip()

    if not code:
        flash('Account code is required', 'danger')
        return redirect(url_for('transaction.flagged_accounts'))

    if transaction_store.add_flagged_account(code, name, reason, auto=False):
        flash(f'Account {code} flagged successfully', 'success')
    else:
        flash('Failed to flag account', 'danger')

    return redirect(url_for('transaction.flagged_accounts'))


@transaction_bp.route('/unflag-account/<flag_id>', methods=['POST'])
def unflag_account(flag_id):
    """Remove a flag from an account."""
    if transaction_store.remove_flagged_account(flag_id):
        flash('Account unflagged', 'success')
    else:
        flash('Failed to unflag account', 'danger')
    return redirect(url_for('transaction.flagged_accounts'))


# ------------------------------------------------------------------
# Export
# ------------------------------------------------------------------
@transaction_bp.route('/export')
def export_transactions():
    """Export transactions to Excel."""
    filters = {}
    if request.args.get('flagged_only'):
        filters['flagged_only'] = True
    if request.args.get('individual_only'):
        filters['individual_only'] = True
    if request.args.get('review_status'):
        filters['review_status'] = request.args.get('review_status')

    filepath = transaction_store.export_to_excel(filters or None)
    if filepath:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return send_file(
            filepath,
            as_attachment=True,
            download_name=f'transactions_export_{timestamp}.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

    flash('No transactions to export', 'warning')
    return redirect(url_for('transaction.dashboard'))


@transaction_bp.route('/import-history')
def import_history():
    """View import history."""
    history = transaction_store.get_import_history()
    history.reverse()
    return render_template('transaction/import_history.html', history=history)


# ------------------------------------------------------------------
# API endpoints for AJAX
# ------------------------------------------------------------------
@transaction_bp.route('/api/stats')
def api_stats():
    """Return summary statistics as JSON."""
    return jsonify(transaction_store.get_summary_statistics())


@transaction_bp.route('/api/bulk-review', methods=['POST'])
def api_bulk_review():
    """Bulk review transactions."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    txn_ids = data.get('transaction_ids', [])
    status = data.get('status', 'approved')
    notes = data.get('notes', '')

    updated = 0
    for tid in txn_ids:
        if transaction_store.update_review_status(tid, status, notes):
            updated += 1

    return jsonify({
        'success': True,
        'message': f'{updated} of {len(txn_ids)} transactions updated to {status}',
    })
