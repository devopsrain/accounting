"""
Backup & Archive Module – Flask Routes

Provides a web dashboard for managing backups:
  - View backup stats and history
  - Trigger manual backup
  - Browse / download / restore / delete archives
  - View scheduler status
  - Configure retention
"""

from flask import (Blueprint, render_template, request, jsonify,
                   session, redirect, url_for, flash, send_file)
from datetime import datetime
import logging

from backup_data_store import backup_engine, backup_scheduler
from auth_data_store import login_required

logger = logging.getLogger(__name__)

backup_bp = Blueprint('backup', __name__, url_prefix='/backup')


# ── Dashboard ─────────────────────────────────────────────────────

@backup_bp.route('/dashboard')
@login_required(min_privilege='operator')
def dashboard():
    """Backup module dashboard."""
    stats = backup_engine.get_stats()
    backups = backup_engine.list_backups()
    log = backup_engine.get_backup_log(limit=20)
    return render_template('backup/dashboard.html',
                           stats=stats, backups=backups, log=log,
                           scheduler_running=backup_scheduler.is_running,
                           next_run=backup_scheduler.next_run)


# ── Manual backup ─────────────────────────────────────────────────

@backup_bp.route('/create', methods=['POST'])
@login_required(min_privilege='admin')
def create_backup():
    """Trigger a manual backup."""
    label = request.form.get('label', '').strip() or None
    user = session.get('username', 'unknown')
    result = backup_engine.create_backup(label=label, triggered_by=f'manual:{user}')

    # Log to SIEM
    try:
        from siem_data_store import siem_store
        siem_store.log_upload_event(
            request, module='backup', endpoint='/backup/create',
            filename=result.get('archive_name', ''),
            file_size=result.get('compressed_size', 0),
            status='success' if result.get('success') else 'failed',
            details=f"Backup: {result.get('file_count',0)} files, "
                    f"{result.get('compressed_size',0):,} bytes compressed",
            user=user,
        )
    except Exception as e:
        logger.warning("SIEM logging failed on backup create: %s", e)

    if result.get('success'):
        flash(f"Backup created: {result['archive_name']} "
              f"({result['file_count']} files, {result['compression_ratio']}% ratio)", 'success')
    else:
        flash(f"Backup failed: {result.get('error', 'Unknown error')}", 'error')
    return redirect(url_for('backup.dashboard'))


# ── Backup details ────────────────────────────────────────────────

@backup_bp.route('/details/<archive_name>')
@login_required(min_privilege='operator')
def backup_details(archive_name):
    """View details of a specific backup."""
    details = backup_engine.get_backup_details(archive_name)
    if not details:
        flash('Backup not found', 'error')
        return redirect(url_for('backup.dashboard'))
    return render_template('backup/details.html', details=details)


# ── Download archive ──────────────────────────────────────────────

@backup_bp.route('/download/<archive_name>')
@login_required(min_privilege='admin')
def download_backup(archive_name):
    """Download a backup archive."""
    import os
    archive_path = os.path.join(backup_engine.backup_dir, archive_name)
    if not os.path.exists(archive_path) or not archive_name.endswith('.zip'):
        flash('Archive not found', 'error')
        return redirect(url_for('backup.dashboard'))
    return send_file(archive_path, as_attachment=True, download_name=archive_name)


# ── Restore ───────────────────────────────────────────────────────

@backup_bp.route('/restore/<archive_name>', methods=['POST'])
@login_required(min_privilege='super_admin')
def restore_backup(archive_name):
    """Restore from a backup archive (super_admin only)."""
    confirm = request.form.get('confirm') == 'yes'
    result = backup_engine.restore_backup(archive_name, confirm=confirm)

    user = session.get('username', 'unknown')
    try:
        from siem_data_store import siem_store
        siem_store.log_upload_event(
            request, module='backup', endpoint='/backup/restore',
            filename=archive_name,
            status='success' if result.get('success') else 'failed',
            details=f"Restored {result.get('restored_files', 0)} files. "
                    f"Safety backup: {result.get('safety_backup', 'none')}",
            user=user,
        )
    except Exception as e:
        logger.warning("SIEM logging failed on backup restore: %s", e)

    if result.get('success'):
        flash(f"Restored {result['restored_files']} files from {archive_name}. "
              f"Safety backup: {result['safety_backup']}", 'success')
    else:
        flash(f"Restore failed: {result.get('error', 'Unknown')}", 'error')
    return redirect(url_for('backup.dashboard'))


# ── Delete ────────────────────────────────────────────────────────

@backup_bp.route('/delete/<archive_name>', methods=['POST'])
@login_required(min_privilege='admin')
def delete_backup(archive_name):
    """Delete a backup archive."""
    if backup_engine.delete_backup(archive_name):
        flash(f'Deleted {archive_name}', 'success')
    else:
        flash('Archive not found', 'error')
    return redirect(url_for('backup.dashboard'))


# ── Purge old backups ─────────────────────────────────────────────

@backup_bp.route('/purge', methods=['POST'])
@login_required(min_privilege='admin')
def purge_old():
    """Purge archives older than retention period."""
    count = backup_engine.purge_old_backups()
    flash(f'Purged {count} old backup(s)', 'success')
    return redirect(url_for('backup.dashboard'))


# ── Scheduler control ─────────────────────────────────────────────

@backup_bp.route('/scheduler/start', methods=['POST'])
@login_required(min_privilege='admin')
def start_scheduler():
    """Start the backup scheduler."""
    backup_scheduler.start()
    flash('Backup scheduler started (daily at 01:00)', 'success')
    return redirect(url_for('backup.dashboard'))


@backup_bp.route('/scheduler/stop', methods=['POST'])
@login_required(min_privilege='admin')
def stop_scheduler():
    """Stop the backup scheduler."""
    backup_scheduler.stop()
    flash('Backup scheduler stopped', 'info')
    return redirect(url_for('backup.dashboard'))


# ── API endpoints ─────────────────────────────────────────────────

@backup_bp.route('/api/stats')
@login_required(min_privilege='operator')
def api_stats():
    """Get backup stats as JSON."""
    return jsonify(backup_engine.get_stats())


@backup_bp.route('/api/list')
@login_required(min_privilege='operator')
def api_list():
    """List all backups as JSON."""
    return jsonify({'backups': backup_engine.list_backups()})
