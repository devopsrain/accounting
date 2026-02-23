"""
Version Control Routes — Ethiopian Accounting System
Blueprint: /version
Provides UI for viewing versions, creating releases, and rolling back.
"""
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify

logger = logging.getLogger(__name__)

version_bp = Blueprint(
    'version',
    __name__,
    url_prefix='/version',
    template_folder='templates',
)


def _get_manager():
    """Lazy-import to avoid circular imports."""
    from version_data_store import version_manager
    return version_manager


# ── Dashboard ─────────────────────────────────────────────────────

@version_bp.route('/')
@version_bp.route('/dashboard')
def dashboard():
    """Version control dashboard — lists all versions with actions."""
    mgr = _get_manager()
    versions = mgr.list_versions()
    current = mgr.get_current_version()
    changelog = mgr.get_changelog()
    return render_template(
        'version/dashboard.html',
        versions=versions,
        current_version=current,
        changelog=changelog,
    )


# ── Create New Version ────────────────────────────────────────────

@version_bp.route('/create', methods=['GET', 'POST'])
def create_version():
    """Form to tag a new version release."""
    mgr = _get_manager()

    if request.method == 'POST':
        version_str = request.form.get('version', '').strip()
        description = request.form.get('description', '').strip()
        released_by = session.get('username', 'admin')
        create_snapshot = request.form.get('create_snapshot', 'on') == 'on'

        if not version_str:
            flash('Version number is required.', 'danger')
            return redirect(url_for('version.create_version'))

        result = mgr.create_version(
            version=version_str,
            description=description,
            released_by=released_by,
            create_snapshot=create_snapshot,
        )

        if result.get('success'):
            flash(f'Version {version_str} released successfully!', 'success')
            return redirect(url_for('version.dashboard'))
        else:
            flash(f'Failed: {result.get("error")}', 'danger')
            return redirect(url_for('version.create_version'))

    # GET — suggest next version number
    current = mgr.get_current_version()
    parts = current.split('.')
    try:
        suggested = f"{parts[0]}.{int(parts[1]) + 1}.0"
    except (IndexError, ValueError):
        suggested = '1.1.0'

    return render_template(
        'version/create.html',
        current_version=current,
        suggested_version=suggested,
    )


# ── Rollback ──────────────────────────────────────────────────────

@version_bp.route('/rollback/<version>', methods=['GET', 'POST'])
def rollback(version):
    """Confirm and execute rollback to a previous version."""
    mgr = _get_manager()
    target = mgr.get_version(version)

    if not target:
        flash(f'Version {version} not found.', 'danger')
        return redirect(url_for('version.dashboard'))

    if request.method == 'POST':
        performed_by = session.get('username', 'admin')
        result = mgr.rollback_to_version(version, performed_by=performed_by)

        if result.get('success'):
            flash(
                f'Successfully rolled back to v{version}. '
                f'{result.get("restored_files", 0)} files restored. '
                f'Safety backup: {result.get("safety_backup", "n/a")}',
                'success',
            )
        else:
            flash(f'Rollback failed: {result.get("error")}', 'danger')

        return redirect(url_for('version.dashboard'))

    return render_template(
        'version/rollback.html',
        target=target,
    )


# ── Delete Version Entry ──────────────────────────────────────────

@version_bp.route('/delete/<version>', methods=['POST'])
def delete_version(version):
    """Delete a non-active version entry."""
    mgr = _get_manager()
    result = mgr.delete_version(version)
    if result.get('success'):
        flash(f'Version {version} removed.', 'success')
    else:
        flash(f'Cannot delete: {result.get("error")}', 'danger')
    return redirect(url_for('version.dashboard'))


# ── API Endpoints ─────────────────────────────────────────────────

@version_bp.route('/api/current')
def api_current_version():
    """Return the current version as JSON (for footer badges, health checks, etc.)."""
    mgr = _get_manager()
    return jsonify({
        'version': mgr.get_current_version(),
        'active': (mgr.get_active_version() or {}),
    })


@version_bp.route('/api/list')
def api_list_versions():
    """Return all versions as JSON."""
    mgr = _get_manager()
    return jsonify({'versions': mgr.list_versions()})
