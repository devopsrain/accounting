"""
Authentication Routes Blueprint

Centralized login/logout/register/user-management routes.
All modules redirect here for authentication.
"""

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from datetime import datetime
import logging
from auth_data_store import auth_store, login_required, PRIVILEGE_LEVELS, PRIVILEGE_DESCRIPTIONS

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


# ── Login / Logout ────────────────────────────────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login page and handler."""
    if session.get('logged_in'):
        return redirect(url_for('auth.portal'))

    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form

        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not username or not password:
            error = 'Username and password are required'
            if request.is_json:
                return jsonify({'success': False, 'error': error}), 400
            flash(error, 'error')
            return render_template('auth/login.html')

        user = auth_store.authenticate(username, password)

        if user:
            auth_store.set_session(user)

            if request.is_json:
                return jsonify({
                    'success': True,
                    'user': user.get('full_name', user['username']),
                    'privilege': user.get('privilege_level', 'viewer'),
                    'redirect': url_for('auth.portal'),
                })
            flash(f"Welcome back, {user.get('full_name', user['username'])}!", 'success')
            return redirect(url_for('auth.portal'))
        else:
            error = 'Invalid credentials or account locked'
            if request.is_json:
                return jsonify({'success': False, 'error': error}), 401
            flash(error, 'error')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
def logout():
    """Log out and clear session."""
    username = session.get('username', 'unknown')
    auth_store.clear_session()
    flash('You have been logged out.', 'info')
    # Log to SIEM
    try:
        from siem_data_store import siem_store
        siem_store.log_upload_event(
            request, module='auth', endpoint='/auth/logout',
            filename='', status='success', user=username,
            details='User logged out'
        )
    except Exception as e:
        logger.warning("SIEM logging failed on logout: %s", e)
    return redirect(url_for('auth.login'))


@auth_bp.route('/access-denied')
def access_denied():
    """Access denied page."""
    return render_template('auth/access_denied.html')


# ── Registration ──────────────────────────────────────────────────

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """New user registration."""
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form

        username = data.get('username', '').strip()
        password = data.get('password', '')
        confirm  = data.get('confirm_password', '')
        full_name = data.get('full_name', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()

        # Validation
        errors = []
        if not username or len(username) < 3:
            errors.append('Username must be at least 3 characters')
        if not password or len(password) < 4:
            errors.append('Password must be at least 4 characters')
        if password != confirm:
            errors.append('Passwords do not match')
        if not full_name:
            errors.append('Full name is required')
        if not email:
            errors.append('Email is required')

        if errors:
            error_msg = '; '.join(errors)
            if request.is_json:
                return jsonify({'success': False, 'error': error_msg}), 400
            flash(error_msg, 'error')
            return render_template('auth/register.html')

        result = auth_store.create_user(
            username=username, password=password,
            full_name=full_name, email=email, phone=phone,
            privilege_level='viewer'  # new users start as viewer
        )

        if result['success']:
            if request.is_json:
                return jsonify({'success': True, 'message': 'Account created. Please login.'})
            flash('Account created successfully! Please login.', 'success')
            return redirect(url_for('auth.login'))
        else:
            if request.is_json:
                return jsonify({'success': False, 'error': result['error']}), 400
            flash(result['error'], 'error')

    return render_template('auth/register.html')


# ── Portal (after login) ─────────────────────────────────────────

@auth_bp.route('/portal')
@login_required
def portal():
    """Main portal page — shows modules user can access."""
    user = auth_store.get_current_user()
    stats = auth_store.get_auth_stats()
    return render_template('auth/portal.html', user=user, stats=stats,
                           privilege_levels=PRIVILEGE_LEVELS,
                           privilege_descriptions=PRIVILEGE_DESCRIPTIONS)


# ── User Management (admin only) ─────────────────────────────────

@auth_bp.route('/users')
@login_required(min_privilege='admin')
def user_management():
    """User management page for admins."""
    users = auth_store.get_all_users()
    stats = auth_store.get_auth_stats()
    login_history = auth_store.get_login_history(limit=50)
    return render_template('auth/users.html', users=users, stats=stats,
                           login_history=login_history,
                           privilege_levels=PRIVILEGE_LEVELS,
                           privilege_descriptions=PRIVILEGE_DESCRIPTIONS)


@auth_bp.route('/users/create', methods=['POST'])
@login_required(min_privilege='admin')
def create_user():
    """Create a new user (admin action)."""
    data = request.get_json()
    result = auth_store.create_user(
        username=data.get('username', '').strip(),
        password=data.get('password', ''),
        full_name=data.get('full_name', '').strip(),
        email=data.get('email', '').strip(),
        phone=data.get('phone', '').strip(),
        privilege_level=data.get('privilege_level', 'viewer'),
    )
    if result['success']:
        return jsonify({'success': True, 'message': 'User created'})
    return jsonify({'success': False, 'error': result['error']}), 400


@auth_bp.route('/users/<user_id>/update', methods=['POST'])
@login_required(min_privilege='admin')
def update_user(user_id):
    """Update user details."""
    data = request.get_json()
    allowed = ['full_name', 'email', 'phone', 'privilege_level', 'is_active']
    updates = {k: v for k, v in data.items() if k in allowed}
    ok = auth_store.update_user(user_id, **updates)
    if ok:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'User not found'}), 404


@auth_bp.route('/users/<user_id>/reset-password', methods=['POST'])
@login_required(min_privilege='admin')
def reset_password(user_id):
    """Reset a user's password."""
    data = request.get_json()
    new_password = data.get('password', '')
    if len(new_password) < 4:
        return jsonify({'success': False, 'error': 'Password too short'}), 400
    ok = auth_store.change_password(user_id, new_password)
    if ok:
        return jsonify({'success': True, 'message': 'Password reset'})
    return jsonify({'success': False, 'error': 'User not found'}), 404


@auth_bp.route('/users/<user_id>/toggle-active', methods=['POST'])
@login_required(min_privilege='admin')
def toggle_active(user_id):
    """Enable/disable user."""
    ok = auth_store.toggle_user_active(user_id)
    if ok:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'User not found'}), 404


@auth_bp.route('/users/<user_id>/delete', methods=['POST'])
@login_required(min_privilege='super_admin')
def delete_user(user_id):
    """Delete a user (super_admin only)."""
    # Prevent self-delete
    if user_id == session.get('user_id'):
        return jsonify({'success': False, 'error': 'Cannot delete your own account'}), 400
    ok = auth_store.delete_user(user_id)
    if ok:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'User not found'}), 404


# ── Change Own Password ──────────────────────────────────────────

@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_own_password():
    """User changes their own password."""
    data = request.get_json()
    current = data.get('current_password', '')
    new_pw  = data.get('new_password', '')
    confirm = data.get('confirm_password', '')

    if new_pw != confirm:
        return jsonify({'success': False, 'error': 'Passwords do not match'}), 400
    if len(new_pw) < 4:
        return jsonify({'success': False, 'error': 'Password too short'}), 400

    # Verify current password
    username = session.get('username')
    user = auth_store.authenticate(username, current)
    if not user:
        return jsonify({'success': False, 'error': 'Current password is incorrect'}), 401

    ok = auth_store.change_password(session.get('user_id'), new_pw)
    if ok:
        return jsonify({'success': True, 'message': 'Password changed'})
    return jsonify({'success': False, 'error': 'Failed to change password'}), 500


# ── Login History API ─────────────────────────────────────────────

@auth_bp.route('/api/login-history')
@login_required(min_privilege='admin')
def api_login_history():
    """Get login history as JSON."""
    limit = request.args.get('limit', 100, type=int)
    history = auth_store.get_login_history(limit=limit)
    return jsonify({'history': history})


@auth_bp.route('/api/stats')
@login_required(min_privilege='admin')
def api_auth_stats():
    """Get auth statistics as JSON."""
    stats = auth_store.get_auth_stats()
    return jsonify(stats)
