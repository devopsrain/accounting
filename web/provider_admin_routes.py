"""
Provider Admin Routes — SaaS Platform Management

Endpoints for the software provider to manage tenants (companies),
subscription tiers, module licenses, and view platform analytics.

Protected by a separate provider-admin password (not regular user auth).
"""

import os
import logging
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session, jsonify,
)

from tenant_data_store import tenant_store, SUBSCRIPTION_TIERS

logger = logging.getLogger(__name__)

provider_admin_bp = Blueprint(
    'provider_admin', __name__,
    url_prefix='/provider',
    template_folder='templates/provider',
)

# Provider admin password — set via env var for production
PROVIDER_ADMIN_PASSWORD = os.environ.get('PROVIDER_ADMIN_PASSWORD', 'provider2026!')


def _require_provider_auth():
    """Check the request has provider-admin privileges."""
    if not session.get('is_provider_admin'):
        return redirect(url_for('provider_admin.provider_login'))
    return None


@provider_admin_bp.before_request
def provider_before_request():
    """Enforce provider-admin auth on every route except login."""
    if request.endpoint == 'provider_admin.provider_login':
        return None
    return _require_provider_auth()


# ── Login ─────────────────────────────────────────────────────────

@provider_admin_bp.route('/login', methods=['GET', 'POST'])
def provider_login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == PROVIDER_ADMIN_PASSWORD:
            session['is_provider_admin'] = True
            flash('Welcome, Provider Admin.', 'success')
            return redirect(url_for('provider_admin.provider_dashboard'))
        flash('Invalid provider password.', 'danger')
    return render_template('provider/login.html')


@provider_admin_bp.route('/logout')
def provider_logout():
    session.pop('is_provider_admin', None)
    flash('Logged out of provider admin.', 'info')
    return redirect(url_for('provider_admin.provider_login'))


# ── Dashboard ─────────────────────────────────────────────────────

@provider_admin_bp.route('/')
@provider_admin_bp.route('/dashboard')
def provider_dashboard():
    stats = tenant_store.get_platform_stats()
    tenants = tenant_store.get_all_tenants()
    return render_template(
        'provider/dashboard.html',
        stats=stats,
        tenants=tenants,
        tiers=SUBSCRIPTION_TIERS,
    )


# ── Tenant Management ────────────────────────────────────────────

@provider_admin_bp.route('/tenants/create', methods=['GET', 'POST'])
def create_tenant():
    if request.method == 'POST':
        data = {
            'company_name': request.form.get('company_name', '').strip(),
            'registration_number': request.form.get('registration_number', '').strip(),
            'tin_number': request.form.get('tin_number', '').strip(),
            'address': request.form.get('address', '').strip(),
            'city': request.form.get('city', 'Addis Ababa').strip(),
            'email': request.form.get('email', '').strip(),
            'phone': request.form.get('phone', '').strip(),
            'business_type': request.form.get('business_type', '').strip(),
            'subscription_tier': request.form.get('subscription_tier', 'starter'),
            'notes': request.form.get('notes', '').strip(),
        }
        if not data['company_name']:
            flash('Company name is required.', 'danger')
            return render_template('provider/create_tenant.html', tiers=SUBSCRIPTION_TIERS)

        tenant = tenant_store.create_tenant(data, created_by='provider_admin')
        flash(f'Tenant "{tenant["company_name"]}" created. '
              f'License key: {tenant["license_key"]}', 'success')
        return redirect(url_for('provider_admin.provider_dashboard'))

    return render_template('provider/create_tenant.html', tiers=SUBSCRIPTION_TIERS)


@provider_admin_bp.route('/tenants/<company_id>')
def view_tenant(company_id):
    tenant = tenant_store.get_tenant(company_id)
    if not tenant:
        flash('Tenant not found.', 'danger')
        return redirect(url_for('provider_admin.provider_dashboard'))

    licenses = tenant_store.get_company_licenses(company_id)
    enabled_modules = tenant_store.get_enabled_modules(company_id)
    audit_log = tenant_store.get_audit_log(company_id, limit=50)
    tier = SUBSCRIPTION_TIERS.get(tenant.get('subscription_tier', 'starter'), {})

    # All possible modules for the toggle UI
    all_modules = sorted({m for t in SUBSCRIPTION_TIERS.values() for m in t['modules']})

    return render_template(
        'provider/view_tenant.html',
        tenant=tenant,
        licenses=licenses,
        enabled_modules=enabled_modules,
        audit_log=audit_log,
        tier=tier,
        tiers=SUBSCRIPTION_TIERS,
        all_modules=all_modules,
    )


@provider_admin_bp.route('/tenants/<company_id>/change-tier', methods=['POST'])
def change_tier(company_id):
    new_tier = request.form.get('subscription_tier', '')
    if new_tier not in SUBSCRIPTION_TIERS:
        flash('Invalid subscription tier.', 'danger')
    elif tenant_store.change_subscription_tier(company_id, new_tier, 'provider_admin'):
        flash(f'Subscription changed to {SUBSCRIPTION_TIERS[new_tier]["display_name"]}.', 'success')
    else:
        flash('Failed to change subscription tier.', 'danger')
    return redirect(url_for('provider_admin.view_tenant', company_id=company_id))


@provider_admin_bp.route('/tenants/<company_id>/suspend', methods=['POST'])
def suspend_tenant(company_id):
    reason = request.form.get('reason', 'Suspended by provider admin')
    tenant_store.suspend_tenant(company_id, reason)
    flash('Tenant suspended.', 'warning')
    return redirect(url_for('provider_admin.view_tenant', company_id=company_id))


@provider_admin_bp.route('/tenants/<company_id>/reactivate', methods=['POST'])
def reactivate_tenant(company_id):
    tenant_store.reactivate_tenant(company_id)
    flash('Tenant reactivated.', 'success')
    return redirect(url_for('provider_admin.view_tenant', company_id=company_id))


# ── Module License Toggle ─────────────────────────────────────────

@provider_admin_bp.route('/tenants/<company_id>/toggle-module', methods=['POST'])
def toggle_module(company_id):
    module_name = request.form.get('module_name', '')
    enable = request.form.get('enable', 'true').lower() in ('true', '1', 'yes')
    tenant_store.toggle_module(company_id, module_name, enable, 'provider_admin')
    state = 'enabled' if enable else 'disabled'
    flash(f'Module "{module_name}" {state}.', 'success')
    return redirect(url_for('provider_admin.view_tenant', company_id=company_id))


# ── API Endpoints (for AJAX) ─────────────────────────────────────

@provider_admin_bp.route('/api/tenants')
def provider_api_tenants():
    return jsonify(tenant_store.get_all_tenants())


@provider_admin_bp.route('/api/tenants/<company_id>/toggle-module', methods=['POST'])
def provider_api_toggle_module(company_id):
    data = request.get_json(force=True) if request.is_json else {}
    module_name = data.get('module_name', request.form.get('module_name', ''))
    enable = data.get('enable', True)
    ok = tenant_store.toggle_module(company_id, module_name, enable, 'provider_admin')
    return jsonify({'success': ok, 'module': module_name, 'enabled': enable})
