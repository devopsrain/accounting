"""
Journal Entry Routes

Flask routes for journal entry management with Excel import/export functionality
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file
from datetime import datetime, date
import logging
import tempfile
import os

from journal_entry_data_store import JournalEntryDataStore

logger = logging.getLogger(__name__)

# Create blueprint
journal_bp = Blueprint('journal_entries', __name__, url_prefix='/journal')

# Create data store
journal_store = JournalEntryDataStore()


@journal_bp.route('/')
def journal_list():
    """List all journal entries"""
    company_id = request.args.get('company_id', 'default')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # Convert date strings if provided
    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None
    
    # Get journal entries
    entries_df = journal_store.read_journal_entries(company_id, start_date_obj, end_date_obj)
    
    # Calculate totals
    total_entries = len(entries_df)
    total_debits = entries_df['total_debit'].sum() if not entries_df.empty else 0
    total_credits = entries_df['total_credit'].sum() if not entries_df.empty else 0
    
    return render_template('journal_entries/list.html',
                         entries=entries_df.to_dict('records'),
                         total_entries=total_entries,
                         total_debits=total_debits,
                         total_credits=total_credits,
                         filters={'company_id': company_id, 'start_date': start_date, 'end_date': end_date})


@journal_bp.route('/view/<entry_id>')
def view_entry(entry_id):
    """View journal entry details"""
    # Get entry and its lines
    entries_df = journal_store.read_journal_entries()
    entry = entries_df[entries_df['entry_id'] == entry_id]
    
    if entry.empty:
        flash('Journal entry not found', 'error')
        return redirect(url_for('journal_entries.journal_list'))
    
    entry_data = entry.iloc[0].to_dict()
    
    # Get entry lines
    lines_df = journal_store.read_entry_lines(entry_id)
    
    return render_template('journal_entries/view.html',
                         entry=entry_data,
                         lines=lines_df.to_dict('records'))


@journal_bp.route('/add', methods=['GET', 'POST'])
def add_entry():
    """Add new journal entry"""
    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form
            
            # Prepare entry data
            entry_data = {
                'company_id': data.get('company_id', 'default'),
                'entry_date': datetime.strptime(data.get('entry_date'), '%Y-%m-%d').date(),
                'description': data.get('description'),
                'reference_number': data.get('reference_number', ''),
            }
            
            # Prepare lines data
            lines_data = []
            total_debit = 0
            total_credit = 0
            
            # Handle multiple lines (assuming JSON format)
            if request.is_json:
                lines = data.get('lines', [])
                for line in lines:
                    debit = float(line.get('debit_amount', 0))
                    credit = float(line.get('credit_amount', 0))
                    
                    lines_data.append({
                        'account_code': line.get('account_code'),
                        'account_name': line.get('account_name', ''),
                        'description': line.get('description', entry_data['description']),
                        'debit_amount': debit,
                        'credit_amount': credit
                    })
                    
                    total_debit += debit
                    total_credit += credit
            
            entry_data['total_debit'] = total_debit
            entry_data['total_credit'] = total_credit
            
            # Validate debits = credits
            if abs(total_debit - total_credit) > 0.01:
                if request.is_json:
                    return jsonify({'success': False, 'error': 'Debits must equal credits'}), 400
                flash('Debits must equal credits', 'error')
                return redirect(request.url)
            
            # Save entry
            entry_id = journal_store.save_journal_entry(entry_data, lines_data)
            
            if request.is_json:
                return jsonify({'success': True, 'entry_id': entry_id})
            
            flash('Journal entry added successfully!', 'success')
            return redirect(url_for('journal_entries.view_entry', entry_id=entry_id))
            
        except Exception as e:
            if request.is_json:
                return jsonify({'success': False, 'error': str(e)}), 400
            flash(f'Error adding entry: {str(e)}', 'error')
    
    return render_template('journal_entries/add.html')


# Excel Import/Export Routes
@journal_bp.route('/export/excel')
def export_excel():
    """Export journal entries to Excel"""
    company_id = request.args.get('company_id')
    
    try:
        filepath = journal_store.export_to_excel(company_id)
        filename = f'journal_entries_{datetime.now().strftime("%Y%m%d")}.xlsx'
        return send_file(filepath, as_attachment=True, download_name=filename)
        
    except Exception as e:
        flash(f'Export failed: {str(e)}', 'error')
        return redirect(url_for('journal_entries.journal_list'))


@journal_bp.route('/import/excel', methods=['GET', 'POST'])
def import_excel():
    """Import journal entries from Excel"""
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
                    result = journal_store.import_from_excel(tmp_file.name, company_id)
                    
                    # Clean up temp file
                    os.unlink(tmp_file.name)
                
                # SIEM: Log upload event
                try:
                    from siem_data_store import siem_store
                    siem_store.log_upload_event(
                        request, module='journal', endpoint='/journal/import/excel',
                        filename=file.filename,
                        records_imported=result.get('imported_count', 0),
                        status='success' if result['success'] else 'failed',
                        details=f"Imported {result.get('imported_count', 0)} journal entries"
                    )
                except Exception as e:
                    logger.warning("SIEM logging failed: %s", e)
                
                if result['success']:
                    flash(f"Successfully imported {result['imported_count']} journal entries!", 'success')
                    if result['errors']:
                        for error in result['errors'][:3]:
                            flash(f"Warning: {error}", 'warning')
                else:
                    flash('Import failed. Please check your file format.', 'error')
                    for error in result['errors'][:3]:
                        flash(f"Error: {error}", 'error')
                        
            except Exception as e:
                # SIEM: Log exception
                try:
                    from siem_data_store import siem_store
                    siem_store.log_upload_event(
                        request, module='journal', endpoint='/journal/import/excel',
                        filename=file.filename if 'file' in dir() else '',
                        status='failed', details=str(e)
                    )
                except Exception as e2:
                    logger.warning("SIEM logging failed: %s", e2)
                flash(f'Import failed: {str(e)}', 'error')
        else:
            flash('Please upload a valid Excel file (.xlsx or .xls)', 'error')
        
        return redirect(url_for('journal_entries.journal_list'))
    
    # GET request - show import form
    return render_template('journal_entries/import_excel.html')


@journal_bp.route('/download/sample')
def download_sample():
    """Download sample journal entries Excel file"""
    try:
        filepath = journal_store.create_sample_excel_file()
        return send_file(filepath, as_attachment=True, download_name='journal_entries_sample_data.xlsx')
        
    except Exception as e:
        flash(f'Sample download failed: {str(e)}', 'error')
        return redirect(url_for('journal_entries.journal_list'))


@journal_bp.route('/dashboard')
def dashboard():
    """Journal entries dashboard"""
    company_id = request.args.get('company_id', 'default')
    
    # Get summary statistics
    entries_df = journal_store.read_journal_entries(company_id)
    
    # Recent entries (last 10)
    recent_entries = entries_df.head(10).to_dict('records') if not entries_df.empty else []
    
    # Monthly summary
    current_month_start = date.today().replace(day=1)
    monthly_entries = journal_store.read_journal_entries(company_id, current_month_start, date.today())
    monthly_count = len(monthly_entries)
    monthly_debits = monthly_entries['total_debit'].sum() if not monthly_entries.empty else 0
    
    stats = {
        'total_entries': len(entries_df),
        'total_debits': entries_df['total_debit'].sum() if not entries_df.empty else 0,
        'total_credits': entries_df['total_credit'].sum() if not entries_df.empty else 0,
        'monthly_entries': monthly_count,
        'monthly_amount': monthly_debits
    }
    
    return render_template('journal_entries/dashboard.html',
                         stats=stats,
                         recent_entries=recent_entries,
                         company_id=company_id)