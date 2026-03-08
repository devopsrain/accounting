"""
Flask Web Interface for the Accounting Software
"""
import logging
import os
import secrets
import sys
import uuid as _uuid

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, g, abort
from flask_wtf.csrf import CSRFProtect
from datetime import datetime, date

# ── Structured Logging Setup ────────────────────────────────────────
# Emits JSON lines when python-json-logger is installed (production);
# falls back to plain text for local development.
try:
    from pythonjsonlogger import jsonlogger as _jlog

    class _RequestIdFilter(logging.Filter):
        """Injects request_id into every log record during a Flask request."""
        def filter(self, record):
            try:
                from flask import g as _g, has_request_context as _hrc
                record.request_id = getattr(_g, 'request_id', '-') if _hrc() else '-'
            except Exception:
                record.request_id = '-'
            return True

    _handler = logging.StreamHandler()
    _handler.setFormatter(_jlog.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s'
    ))
    _handler.addFilter(_RequestIdFilter())
    logging.root.handlers.clear()
    logging.root.addHandler(_handler)
    logging.root.setLevel(logging.INFO)
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
logger = logging.getLogger(__name__)

# Add the parent directory to the path for model/core imports (single entry point)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── AWS Secrets Manager (no-op in local dev / outside AWS) ───────────────
# Called before any os.environ.get() so secrets are available at config time.
try:
    from secrets_loader import load_secrets
    load_secrets()
except ImportError:
    pass

from models.account import Account, AccountType, AccountSubType
from models.journal_entry import JournalEntry, JournalEntryBuilder
from core.ledger import GeneralLedger

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)
if not os.environ.get('FLASK_SECRET_KEY'):
    logging.getLogger(__name__).warning(
        'FLASK_SECRET_KEY not set — using random key (sessions reset on restart). '
        'Set FLASK_SECRET_KEY env var for production.'
    )

# ── Secure Cookie Configuration ───────────────────────────────────
# SESSION_COOKIE_SECURE=True requires HTTPS; honour env var so local dev works.
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get(
    'SESSION_COOKIE_SECURE', '0'
).lower() in ('1', 'true', 'yes')

# ── CSRF Protection ───────────────────────────────────────────────
csrf = CSRFProtect(app)

# ── Rate Limiter & Response Cache ───────────────────────────────────
from extensions import limiter, cache, LIMITER_AVAILABLE, CACHE_AVAILABLE
limiter.init_app(app)
if CACHE_AVAILABLE:
    cache.init_app(app, config={
        'CACHE_TYPE': 'SimpleCache',
        'CACHE_DEFAULT_TIMEOUT': 300,
    })

import re as _re
from flask_wtf.csrf import generate_csrf

@app.after_request
def inject_csrf_token(response):
    """Auto-inject CSRF hidden input into every POST form in HTML responses."""
    if response.content_type and 'text/html' in response.content_type:
        token = generate_csrf()
        hidden = f'<input type="hidden" name="csrf_token" value="{token}">'
        data = response.get_data(as_text=True)
        # Insert hidden input right after every <form ...> that uses POST
        data = _re.sub(
            r'(<form\b[^>]*method=["\']?post["\']?[^>]*>)',
            r'\1' + hidden,
            data,
            flags=_re.IGNORECASE,
        )
        response.set_data(data)
    return response


# ── Request ID Tracking ──────────────────────────────────────────
@app.before_request
def _set_request_id():
    """Attach a short request ID to g for correlated logging and response headers."""
    g.request_id = request.headers.get('X-Request-ID') or _uuid.uuid4().hex[:12]


@app.after_request
def _add_request_id_header(response):
    """Echo the request ID so callers can correlate logs with responses."""
    response.headers['X-Request-ID'] = getattr(g, 'request_id', '-')
    return response


# Global ledger instance
ledger = GeneralLedger()

# ── Strict Authentication Gate ────────────────────────────────────
# Every request MUST be authenticated except for the explicit whitelist
# below. This ensures no route — present or future — is ever accessible
# without logging in.
PUBLIC_ENDPOINTS = frozenset({
    'auth.login',
    'auth.logout',
    'auth.register',
    'auth.access_denied',
    'multicompany.company_login',     # multi-company portal login
    'multicompany.company_register',  # multi-company portal register
    'static',                         # CSS / JS / images
    'provider_admin.provider_dashboard',  # provider login handled internally
    'provider_admin.provider_login',
    'provider_admin.provider_api_tenants',
    'provider_admin.provider_api_toggle_module',
    'sales.landing',                  # public sales / marketing site
    'sales.contact',                  # contact-form handler
    'health_check',                   # ALB / monitoring health endpoint
})

# URL prefixes that are always public (login-related paths).
# This is a safety net in case blueprint names change.
PUBLIC_PREFIXES = ('/auth/login', '/auth/logout', '/auth/register',
                   '/auth/access-denied', '/company/login', '/company/register',
                   '/static/', '/provider/', '/sales/', '/health')

# ── Multi-Tenant Context & Module Licensing ───────────────────────
# After authentication, every request gets a company context set on g.
# Then the module licensing gate checks the company's subscription allows
# access to the requested module.

from tenant_data_store import (
    tenant_store, BLUEPRINT_TO_MODULE, ALWAYS_ALLOWED_MODULES,
    SUBSCRIPTION_TIERS,
)

# Endpoints exempt from company-context and module-license checks.
# These are system-level or provider-level routes.
LICENSE_EXEMPT_ENDPOINTS = frozenset({
    'auth.login', 'auth.logout', 'auth.register', 'auth.access_denied',
    'auth.portal', 'auth.users', 'auth.create_user', 'auth.delete_user',
    'auth.change_password', 'auth.my_account',
    'multicompany.company_login', 'multicompany.company_register',
    'multicompany.company_select', 'multicompany.company_switch',
    'static', 'index',
    'sales.landing', 'sales.contact',
})
LICENSE_EXEMPT_PREFIXES = (
    '/auth/', '/company/login', '/company/register',
    '/company/select', '/static/', '/provider/', '/sales/',
)


@app.before_request
def require_login_globally():
    """Redirect every unauthenticated request to the login page."""
    # Allow health-check / favicon / static assets through
    if request.path == '/health' or request.path.startswith('/static/') or request.path == '/favicon.ico':
        return None

    # Allow explicitly public endpoints
    endpoint = request.endpoint
    if endpoint and endpoint in PUBLIC_ENDPOINTS:
        return None

    # Safety-net: also match by URL path
    for prefix in PUBLIC_PREFIXES:
        if request.path.startswith(prefix):
            return None

    # If not logged in — try Bearer token, then redirect/401
    if not session.get('logged_in'):
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            from auth_data_store import auth_store as _auth_store
            token_user = _auth_store.validate_api_token(auth_header[7:].strip())
            if token_user:
                g.api_user = token_user
                return None
            return jsonify({'error': 'Invalid or expired API token', 'status': 401}), 401
        # Return JSON 401 for API/AJAX paths; HTML redirect for browser paths
        if request.path.startswith('/api/') or request.is_json:
            return jsonify({'error': 'Authentication required', 'status': 401}), 401
        flash('Please log in to continue.', 'warning')
        try:
            return redirect(url_for('auth.login'))
        except Exception:
            return redirect('/auth/login')


@app.before_request
def set_company_context():
    """Inject g.company_id for every authenticated request.

    Sources (in priority order):
      1. session['current_company_id'] (set at login or company-switch)
      2. Default tenant from the platform (auto-created on first run)

    Also sets g.tenant with the full tenant record.
    Tenant lookups are cached for 60 s to avoid a DB round-trip on every request.
    """
    if not session.get('logged_in') and not getattr(g, 'api_user', None):
        g.company_id = None
        g.tenant = None
        return None

    company_id = session.get('current_company_id')

    if not company_id:
        # Fall back to default tenant
        company_id = tenant_store.ensure_default_tenant()
        session['current_company_id'] = company_id

    g.company_id = company_id

    # Cache tenant record for 60 s — avoids a DB round-trip on every request
    _cache_key = f'tenant:{company_id}'
    g.tenant = cache.get(_cache_key)
    if g.tenant is None:
        g.tenant = tenant_store.get_tenant(company_id)
        if g.tenant:
            cache.set(_cache_key, g.tenant, timeout=60)

    # If tenant doesn't exist yet (e.g. legacy data), auto-create it
    if g.tenant is None:
        tenant_store.create_tenant({
            'company_id': company_id,
            'company_name': session.get('company_name', 'My Company'),
            'subscription_tier': 'enterprise',
        }, created_by=session.get('username', 'system'))
        g.tenant = tenant_store.get_tenant(company_id)
        if g.tenant:
            cache.set(_cache_key, g.tenant, timeout=60)


@app.before_request
def enforce_module_license():
    """Block access to modules the company has not licensed.

    Checks the requested blueprint against the company's licensed modules.
    Returns 403 if the module is not licensed.
    """
    # Skip for unauthenticated requests (handled by require_login_globally)
    if not session.get('logged_in'):
        return None

    # Skip system/provider/auth routes
    endpoint = request.endpoint or ''
    if endpoint in LICENSE_EXEMPT_ENDPOINTS:
        return None
    for prefix in LICENSE_EXEMPT_PREFIXES:
        if request.path.startswith(prefix):
            return None

    # Determine which module this route belongs to
    blueprint_name = request.blueprints[0] if request.blueprints else ''
    module_name = BLUEPRINT_TO_MODULE.get(blueprint_name) or \
                  BLUEPRINT_TO_MODULE.get(endpoint.split('.')[0] if '.' in endpoint else '')

    if not module_name or module_name in ALWAYS_ALLOWED_MODULES:
        return None

    company_id = getattr(g, 'company_id', None)
    if not company_id:
        return None  # no tenant context — allow (single-company mode)

    # Check subscription is active
    if not tenant_store.is_subscription_active(company_id):
        flash('Your company subscription has expired or been suspended. '
              'Contact the system administrator.', 'danger')
        return redirect(url_for('auth.portal'))

    # Check module is licensed
    if not tenant_store.is_module_licensed(company_id, module_name):
        tenant = getattr(g, 'tenant', {}) or {}
        tier = tenant.get('subscription_tier', 'starter')
        tier_info = SUBSCRIPTION_TIERS.get(tier, {})
        flash(
            f'The "{module_name.replace("_", " ").title()}" module is not included '
            f'in your {tier_info.get("display_name", tier)} subscription. '
            f'Contact your administrator to upgrade.',
            'warning'
        )
        return redirect(url_for('auth.portal'))


@app.context_processor
def inject_tenant_context():
    """Make tenant info available in all templates."""
    return {
        'current_company_id': getattr(g, 'company_id', None),
        'current_tenant': getattr(g, 'tenant', None),
    }

# ── Module Registration ───────────────────────────────────────────
# Each module is imported and registered; ImportError means the module
# file is missing (degraded mode), any other exception is a real bug.

try:
    from auth_routes import auth_bp
    app.register_blueprint(auth_bp)
    logger.info("Authentication system integrated")
except ImportError as e:
    logger.warning("Authentication system not available: %s", e)
except Exception as e:
    logger.error("Error initializing authentication system: %s", e, exc_info=True)

try:
    from provider_admin_routes import provider_admin_bp
    app.register_blueprint(provider_admin_bp)
    logger.info("Provider admin dashboard integrated")
except ImportError as e:
    logger.warning("Provider admin dashboard not available: %s", e)
except Exception as e:
    logger.error("Error initializing Provider admin dashboard: %s", e, exc_info=True)

try:
    from sales_routes import sales_bp
    app.register_blueprint(sales_bp)
    logger.info("Sales marketing site integrated")
except ImportError as e:
    logger.warning("Sales marketing site not available: %s", e)
except Exception as e:
    logger.error("Error initializing sales site: %s", e, exc_info=True)

try:
    from payroll_routes import add_payroll_routes
    add_payroll_routes(app, ledger)
    logger.info("Ethiopian payroll system integrated")
except ImportError as e:
    logger.warning("Ethiopian payroll system not available: %s", e)
except Exception as e:
    logger.error("Error initializing payroll system: %s", e, exc_info=True)

try:
    from multicompany_routes import multicompany_bp
    app.register_blueprint(multicompany_bp)
    logger.info("Multi-company user portal integrated")
except ImportError as e:
    logger.warning("Multi-company portal not available: %s", e)
except Exception as e:
    logger.error("Error initializing multi-company portal: %s", e, exc_info=True)

try:
    from vat_routes import vat_bp
    app.register_blueprint(vat_bp, url_prefix='/vat')
    logger.info("VAT portal integrated")
except ImportError as e:
    logger.warning("VAT portal not available: %s", e)
except Exception as e:
    logger.error("Error initializing VAT portal: %s", e, exc_info=True)

try:
    from journal_entry_routes import journal_bp
    app.register_blueprint(journal_bp, url_prefix='/journal')
    logger.info("Journal entry system integrated")
except ImportError as e:
    logger.warning("Journal entry system not available: %s", e)
except Exception as e:
    logger.error("Error initializing journal entry system: %s", e, exc_info=True)

try:
    from chart_of_accounts_routes import accounts_bp
    app.register_blueprint(accounts_bp, url_prefix='/accounts')
    logger.info("Chart of accounts system integrated")
except ImportError as e:
    logger.warning("Chart of accounts system not available: %s", e)
except Exception as e:
    logger.error("Error initializing chart of accounts system: %s", e, exc_info=True)

try:
    from income_expense_routes import income_expense_bp
    app.register_blueprint(income_expense_bp, url_prefix='/income-expense')
    logger.info("Income & Expense system integrated")
except ImportError as e:
    logger.warning("Income & Expense system not available: %s", e)
except Exception as e:
    logger.error("Error initializing Income & Expense system: %s", e, exc_info=True)

try:
    from transaction_routes import transaction_bp
    app.register_blueprint(transaction_bp, url_prefix='/transactions')
    logger.info("Transaction system integrated")
except ImportError as e:
    logger.warning("Transaction system not available: %s", e)
except Exception as e:
    logger.error("Error initializing Transaction system: %s", e, exc_info=True)

try:
    from cpo_routes import cpo_bp
    app.register_blueprint(cpo_bp, url_prefix='/cpo')
    logger.info("CPO system integrated")
except ImportError as e:
    logger.warning("CPO system not available: %s", e)
except Exception as e:
    logger.error("Error initializing CPO system: %s", e, exc_info=True)

try:
    from inventory_routes import inventory_bp
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    logger.info("Inventory system integrated")
except ImportError as e:
    logger.warning("Inventory system not available: %s", e)
except Exception as e:
    logger.error("Error initializing Inventory system: %s", e, exc_info=True)

try:
    from bid_routes import bid_bp
    app.register_blueprint(bid_bp, url_prefix='/bid')
    logger.info("Bid Tracker system integrated")
except ImportError as e:
    logger.warning("Bid Tracker system not available: %s", e)
except Exception as e:
    logger.error("Error initializing Bid Tracker system: %s", e, exc_info=True)

try:
    from siem_routes import siem_bp
    app.register_blueprint(siem_bp, url_prefix='/siem')
    logger.info("SIEM system integrated")
except ImportError as e:
    logger.warning("SIEM system not available: %s", e)
except Exception as e:
    logger.error("Error initializing SIEM system: %s", e, exc_info=True)

try:
    from backup_routes import backup_bp
    from backup_data_store import backup_scheduler
    app.register_blueprint(backup_bp)
    backup_scheduler.start()
    logger.info("Backup & Archive system integrated (scheduler at 01:00)")
except ImportError as e:
    logger.warning("Backup system not available: %s", e)
except Exception as e:
    logger.error("Error initializing Backup system: %s", e, exc_info=True)

try:
    from version_routes import version_bp
    from version_data_store import version_manager
    app.register_blueprint(version_bp)
    # Seed v1.0.0 on first startup if no versions exist yet
    version_manager.seed_initial_version()
    logger.info("Version control system integrated (v%s)", version_manager.get_current_version())
except ImportError as e:
    logger.warning("Version control system not available: %s", e)
except Exception as e:
    logger.error("Error initializing Version control system: %s", e, exc_info=True)

# ── Inject app_version into all templates ─────────────────────────
@app.context_processor
def inject_app_version():
    try:
        from version_data_store import version_manager
        return {'app_version': version_manager.get_current_version()}
    except Exception:
        return {'app_version': '1.0.0'}


@app.route('/')
def index():
    """Landing page — always the login screen (or portal if already logged in)."""
    if session.get('logged_in'):
        return redirect('/auth/portal')
    return redirect('/auth/login')


@app.route('/setup')
def setup():
    return redirect('/accounts/dashboard')


@app.route('/setup', methods=['POST'])
def setup_accounts():
    return redirect('/accounts/dashboard')


@app.route('/accounts')
def accounts():
    return redirect('/accounts/')


@app.route('/accounts/new')
def new_account():
    return redirect('/accounts/add')


@app.route('/accounts/new', methods=['POST'])
def create_account():
    return redirect('/accounts/add')


@app.route('/journal-entry', methods=['GET', 'POST'])
def journal_entry_form():
    return redirect('/journal/')


@app.route('/quick-transactions')
def quick_transactions():
    return redirect('/transactions/')


@app.route('/quick-sale', methods=['POST'])
def quick_sale():
    return redirect('/transactions/')


@app.route('/quick-expense', methods=['POST'])
def quick_expense():
    return redirect('/transactions/')


@app.route('/reports/trial-balance')
def trial_balance():
    return redirect('/accounts/trial-balance')


@app.route('/reports/income-statement')
def income_statement():
    return redirect('/income-expense/')


@app.route('/reports/balance-sheet')
def balance_sheet():
    return redirect('/accounts/dashboard')


@app.route('/reports/account-ledger/<account_id>')
def account_ledger(account_id):
    return redirect(f'/accounts/view/{account_id}')


@app.route('/export')
def export_data():
    return redirect('/accounts/export/excel')


@app.route('/api/accounts')
def api_accounts():
    return redirect('/accounts/')


# ── Health Check Endpoint ────────────────────────────────────────
@app.route('/health')
def health_check():
    """AWS ALB / monitoring health endpoint.

    Returns HTTP 200 + JSON when everything is healthy,
    HTTP 503 + JSON when the database is unreachable.
    """
    from db import health_check as db_health
    db = db_health()
    payload = {
        'status': 'ok' if db['ok'] else 'degraded',
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'database': db,
    }
    http_status = 200 if db['ok'] else 503
    if not db['ok']:
        logger.error('Health check: DB unreachable — %s', db.get('error'))
    return jsonify(payload), http_status


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found', 'status': 404}), 404
    try:
        return render_template('errors/404.html'), 404
    except Exception:
        return '<h1>404 — Page Not Found</h1><p><a href="/">Back to Home</a></p>', 404


@app.errorhandler(500)
def server_error(e):
    logger.error("500 Internal Server Error: %s", e, exc_info=True)
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal server error', 'status': 500}), 500
    try:
        return render_template('errors/500.html'), 500
    except Exception:
        return '<h1>500 — Internal Server Error</h1><p>Something went wrong. <a href="/">Back to Home</a></p>', 500


if __name__ == '__main__':
    # Create templates directory structure if it doesn't exist
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
    
    logger.info("Starting Accounting Software Web Interface...")
    logger.info("Access the application at: http://localhost:5000")
    debug_mode = os.environ.get('FLASK_DEBUG', '0').lower() in ('1', 'true', 'yes')
    app.run(debug=debug_mode, host='localhost', port=5000)