"""
Bid Tracking Routes

Flask Blueprint for public bid tracking with document management,
team collaboration, and deadline email reminders.
"""

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, send_file, jsonify, abort,
)
import os
from datetime import datetime

from bid_data_store import bid_store

try:
    from siem_data_store import siem_store
except ImportError:
    siem_store = None

bid_bp = Blueprint('bid', __name__, template_folder='templates')

ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'txt', 'csv', 'zip', 'rar', '7z',
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg',
}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Dashboard ─────────────────────────────────────────────────────
@bid_bp.route('/')
@bid_bp.route('/dashboard')
def dashboard():
    stats = bid_store.get_summary_stats()
    bids = bid_store.get_all_bids()
    bids.reverse()  # newest first
    return render_template('bid/dashboard.html', stats=stats, bids=bids)


# ── Add / Create Bid ─────────────────────────────────────────────
@bid_bp.route('/add', methods=['GET', 'POST'])
def add_bid():
    if request.method == 'POST':
        data = {
            'title': request.form.get('title', '').strip(),
            'reference_number': request.form.get('reference_number', '').strip(),
            'organization': request.form.get('organization', '').strip(),
            'description': request.form.get('description', '').strip(),
            'category': request.form.get('category', '').strip(),
            'status': request.form.get('status', 'Draft'),
            'deadline': request.form.get('deadline', '').strip(),
            'bid_amount': request.form.get('bid_amount', 0),
            'currency': request.form.get('currency', 'ETB'),
            'case_handler_name': request.form.get('case_handler_name', '').strip(),
            'case_handler_email': request.form.get('case_handler_email', '').strip(),
            'reminder_days_before': request.form.get('reminder_days_before', 3),
            'notes': request.form.get('notes', '').strip(),
        }
        if not data['title']:
            flash('Bid title is required', 'error')
            return render_template('bid/add_bid.html', bid=data)

        bid_id = bid_store.save_bid(data)
        if bid_id:
            if siem_store:
                siem_store.log_upload_event(
                    request, module='bid', endpoint='/bid/add',
                    filename='', status='success',
                    details=f'Created bid {bid_id}: {data["title"]}',
                )
            flash('Bid created successfully!', 'success')
            return redirect(url_for('bid.view_bid', bid_id=bid_id))
        flash('Error creating bid', 'error')
        return render_template('bid/add_bid.html', bid=data)

    return render_template('bid/add_bid.html', bid={})


# ── View Bid Detail ───────────────────────────────────────────────
@bid_bp.route('/view/<bid_id>')
def view_bid(bid_id):
    bid = bid_store.get_bid_by_id(bid_id)
    if not bid:
        flash('Bid not found', 'error')
        return redirect(url_for('bid.dashboard'))

    # Group documents by type
    doc_groups = {
        'original_bid': [],
        'technical': [],
        'financial': [],
        'supporting': [],
        'other': [],
    }
    for doc in bid.get('documents', []):
        dtype = doc.get('doc_type', 'other')
        if dtype in doc_groups:
            doc_groups[dtype].append(doc)
        else:
            doc_groups['other'].append(doc)

    return render_template('bid/view_bid.html', bid=bid, doc_groups=doc_groups)


# ── Edit Bid ──────────────────────────────────────────────────────
@bid_bp.route('/edit/<bid_id>', methods=['GET', 'POST'])
def edit_bid(bid_id):
    bid = bid_store.get_bid_by_id(bid_id)
    if not bid:
        flash('Bid not found', 'error')
        return redirect(url_for('bid.dashboard'))

    if request.method == 'POST':
        data = {
            'id': bid_id,
            'title': request.form.get('title', '').strip(),
            'reference_number': request.form.get('reference_number', '').strip(),
            'organization': request.form.get('organization', '').strip(),
            'description': request.form.get('description', '').strip(),
            'category': request.form.get('category', '').strip(),
            'status': request.form.get('status', bid['status']),
            'deadline': request.form.get('deadline', '').strip(),
            'submission_date': request.form.get('submission_date', '').strip(),
            'bid_amount': request.form.get('bid_amount', 0),
            'currency': request.form.get('currency', 'ETB'),
            'case_handler_name': request.form.get('case_handler_name', '').strip(),
            'case_handler_email': request.form.get('case_handler_email', '').strip(),
            'reminder_days_before': request.form.get('reminder_days_before', 3),
            'notes': request.form.get('notes', '').strip(),
        }
        if not data['title']:
            flash('Bid title is required', 'error')
            return render_template('bid/edit_bid.html', bid=data)

        result = bid_store.save_bid(data)
        if result:
            flash('Bid updated successfully!', 'success')
            return redirect(url_for('bid.view_bid', bid_id=bid_id))
        flash('Error updating bid', 'error')

    return render_template('bid/edit_bid.html', bid=bid)


# ── Upload Document ───────────────────────────────────────────────
@bid_bp.route('/upload/<bid_id>', methods=['POST'])
def upload_document(bid_id):
    bid = bid_store.get_bid_by_id(bid_id)
    if not bid:
        flash('Bid not found', 'error')
        return redirect(url_for('bid.dashboard'))

    if 'file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('bid.view_bid', bid_id=bid_id))

    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('bid.view_bid', bid_id=bid_id))

    if not _allowed_file(file.filename):
        flash('File type not allowed. Allowed: PDF, Office, images, text, archives.', 'error')
        return redirect(url_for('bid.view_bid', bid_id=bid_id))

    doc_type = request.form.get('doc_type', 'other')
    description = request.form.get('description', '').strip()
    uploaded_by = request.form.get('uploaded_by', '').strip()

    doc_id = bid_store.save_document(bid_id, file, doc_type, description, uploaded_by)
    if doc_id:
        if siem_store:
            siem_store.log_upload_event(
                request, module='bid', endpoint=f'/bid/upload/{bid_id}',
                filename=file.filename, status='success',
                details=f'Uploaded {doc_type} document for bid {bid_id}',
            )
        flash(f'Document "{file.filename}" uploaded successfully!', 'success')
    else:
        flash('Error uploading document', 'error')

    return redirect(url_for('bid.view_bid', bid_id=bid_id))


# ── Download Document ─────────────────────────────────────────────
@bid_bp.route('/download/<bid_id>/<doc_id>')
def download_document(bid_id, doc_id):
    path = bid_store.get_document_path(bid_id, doc_id)
    if not path:
        flash('Document not found', 'error')
        return redirect(url_for('bid.view_bid', bid_id=bid_id))

    meta = bid_store.get_document_meta(doc_id)
    original_name = meta.get('original_filename', 'document') if meta else 'document'

    return send_file(path, as_attachment=True, download_name=original_name)


# ── View Document Online ──────────────────────────────────────────
@bid_bp.route('/preview/<bid_id>/<doc_id>')
def preview_document(bid_id, doc_id):
    path = bid_store.get_document_path(bid_id, doc_id)
    if not path:
        flash('Document not found', 'error')
        return redirect(url_for('bid.view_bid', bid_id=bid_id))

    meta = bid_store.get_document_meta(doc_id)
    return send_file(path, as_attachment=False)


# ── Delete Document ───────────────────────────────────────────────
@bid_bp.route('/delete-doc/<bid_id>/<doc_id>', methods=['POST'])
def delete_document(bid_id, doc_id):
    if bid_store.delete_document(doc_id):
        flash('Document deleted', 'success')
    else:
        flash('Error deleting document', 'error')
    return redirect(url_for('bid.view_bid', bid_id=bid_id))


# ── Delete Bid ────────────────────────────────────────────────────
@bid_bp.route('/delete/<bid_id>', methods=['POST'])
def delete_bid(bid_id):
    if bid_store.delete_bid(bid_id):
        flash('Bid deleted', 'success')
    else:
        flash('Error deleting bid', 'error')
    return redirect(url_for('bid.dashboard'))


# ── Test Email ────────────────────────────────────────────────────
@bid_bp.route('/test-email', methods=['POST'])
def test_email():
    email = request.form.get('email', '').strip()
    if not email:
        flash('Email address is required', 'error')
        return redirect(request.referrer or url_for('bid.dashboard'))

    result = bid_store.send_test_email(email)
    if result['success']:
        flash(result['message'], 'success')
    else:
        flash(result['message'], 'error')
    return redirect(request.referrer or url_for('bid.dashboard'))


# ── API: Summary Stats ────────────────────────────────────────────
@bid_bp.route('/api/stats')
def api_stats():
    return jsonify(bid_store.get_summary_stats())
