"""
CPO (Cash Payment Order) Routes

Flask Blueprint for Cash Payment Order management with Excel import/export.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify
import pandas as pd
import os
from datetime import datetime

from cpo_data_store import CPODataStore
from siem_data_store import siem_store

cpo_bp = Blueprint('cpo', __name__, template_folder='templates')
cpo_store = CPODataStore(data_dir='data')


@cpo_bp.route('/')
def dashboard():
    """CPO dashboard with summary statistics."""
    summary = cpo_store.get_summary()
    recent_cpos = cpo_store.get_all_cpos()[-10:]  # last 10
    recent_cpos.reverse()
    import_history = cpo_store.get_import_history()[-5:]
    import_history.reverse()

    return render_template(
        'cpo/dashboard.html',
        summary=summary,
        recent_cpos=recent_cpos,
        import_history=import_history,
    )


@cpo_bp.route('/import', methods=['GET', 'POST'])
def import_excel():
    """Import CPO records from Excel file."""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)

        if not file.filename.lower().endswith(('.xlsx', '.xls')):
            flash('Please upload an Excel file (.xlsx or .xls)', 'error')
            return redirect(request.url)

        try:
            df = pd.read_excel(file, sheet_name=0)

            if df.empty:
                flash('The uploaded file contains no data', 'error')
                return redirect(request.url)

            result = cpo_store.import_from_dataframe(df, file.filename)

            # SIEM: Log successful upload
            siem_store.log_upload_event(
                request, module='cpo', endpoint='/cpo/import',
                filename=file.filename, records_imported=result.get('imported', 0),
                status='success', details=f"Imported {result.get('imported', 0)} CPO records"
            )

            return render_template(
                'cpo/import_result.html',
                result=result,
                filename=file.filename,
            )

        except Exception as e:
            # SIEM: Log failed upload
            siem_store.log_upload_event(
                request, module='cpo', endpoint='/cpo/import',
                filename=file.filename if 'file' in dir() else '',
                status='failed', details=str(e)
            )
            flash(f'Error reading Excel file: {str(e)}', 'error')
            return redirect(request.url)

    return render_template('cpo/import.html')


@cpo_bp.route('/list')
def cpo_list():
    """List all CPO records."""
    records = cpo_store.get_all_cpos()
    records.reverse()  # newest first
    summary = cpo_store.get_summary()
    return render_template('cpo/cpo_list.html', records=records, summary=summary)


@cpo_bp.route('/add', methods=['GET', 'POST'])
def add_cpo():
    """Add a single CPO record manually."""
    if request.method == 'POST':
        is_returned = request.form.get('is_returned', 'No')
        returned_date = request.form.get('returned_date', '').strip()

        # Validate: if returned, date is mandatory
        if is_returned == 'Yes' and not returned_date:
            flash('Returned date is required when CPO is marked as returned', 'error')
            record = {
                'name': request.form.get('name', '').strip(),
                'date': request.form.get('date', ''),
                'amount': request.form.get('amount', ''),
                'bid_name': request.form.get('bid_name', '').strip(),
                'is_returned': is_returned,
                'returned_date': returned_date,
            }
            return render_template('cpo/add_cpo.html', record=record)

        record = {
            'name': request.form.get('name', '').strip(),
            'date': request.form.get('date', datetime.now().strftime('%Y-%m-%d')),
            'amount': float(request.form.get('amount', 0)),
            'bid_name': request.form.get('bid_name', '').strip(),
            'is_returned': is_returned,
            'returned_date': returned_date if is_returned == 'Yes' else '',
        }

        if not record['name']:
            flash('Name is required', 'error')
            return render_template('cpo/add_cpo.html', record=record)

        if cpo_store.save_cpo(record):
            flash('CPO record added successfully!', 'success')
            return redirect(url_for('cpo.cpo_list'))
        else:
            flash('Error saving CPO record', 'error')
            return render_template('cpo/add_cpo.html', record=record)

    return render_template('cpo/add_cpo.html', record={})


@cpo_bp.route('/edit/<cpo_id>', methods=['GET', 'POST'])
def edit_cpo(cpo_id):
    """Edit an existing CPO record."""
    record = cpo_store.get_cpo_by_id(cpo_id)
    if not record:
        flash('CPO record not found', 'error')
        return redirect(url_for('cpo.cpo_list'))

    if request.method == 'POST':
        is_returned = request.form.get('is_returned', 'No')
        returned_date = request.form.get('returned_date', '').strip()

        # Validate: if returned, date is mandatory
        if is_returned == 'Yes' and not returned_date:
            flash('Returned date is required when CPO is marked as returned', 'error')
            record.update({
                'name': request.form.get('name', '').strip(),
                'date': request.form.get('date', ''),
                'amount': request.form.get('amount', ''),
                'bid_name': request.form.get('bid_name', '').strip(),
                'is_returned': is_returned,
                'returned_date': returned_date,
            })
            return render_template('cpo/edit_cpo.html', record=record)

        updates = {
            'name': request.form.get('name', '').strip(),
            'date': request.form.get('date', ''),
            'amount': float(request.form.get('amount', 0)),
            'bid_name': request.form.get('bid_name', '').strip(),
            'is_returned': is_returned,
            'returned_date': returned_date if is_returned == 'Yes' else '',
        }

        if not updates['name']:
            flash('Name is required', 'error')
            record.update(updates)
            return render_template('cpo/edit_cpo.html', record=record)

        if cpo_store.update_cpo(cpo_id, updates):
            flash('CPO record updated successfully!', 'success')
            return redirect(url_for('cpo.cpo_list'))
        else:
            flash('Error updating CPO record', 'error')
            record.update(updates)
            return render_template('cpo/edit_cpo.html', record=record)

    return render_template('cpo/edit_cpo.html', record=record)


@cpo_bp.route('/delete/<cpo_id>', methods=['POST'])
def delete_cpo(cpo_id):
    """Delete a CPO record."""
    if cpo_store.delete_cpo(cpo_id):
        flash('CPO record deleted', 'success')
    else:
        flash('Error deleting CPO record', 'error')
    return redirect(url_for('cpo.cpo_list'))


@cpo_bp.route('/export')
def export_excel():
    """Export all CPO records to Excel."""
    filepath = cpo_store.export_to_excel()
    if filepath:
        return send_file(
            filepath,
            as_attachment=True,
            download_name=f"cpo_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        )
    flash('Error exporting data', 'error')
    return redirect(url_for('cpo.dashboard'))


@cpo_bp.route('/download-template')
def download_template():
    """Download CPO import template Excel file."""
    filepath = cpo_store.generate_sample_excel()
    if filepath:
        return send_file(
            filepath,
            as_attachment=True,
            download_name='CPO_Import_Template.xlsx',
        )
    flash('Error generating template', 'error')
    return redirect(url_for('cpo.import_excel'))
