"""
Flask Web Interface for the Accounting Software
"""
import logging
import os
import secrets
import sys

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, g, abort
from flask_wtf.csrf import CSRFProtect
from datetime import datetime, date

# ── Logging Setup ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

# Add the parent directory to the path for model/core imports (single entry point)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

# Global ledger instance
ledger = GeneralLedger()

# ── Strict Authentication Gate ────────────────────────────────────
# Every request MUST be authenticated except for the explicit whitelist
# below. This ensures no route — present or future — is ever accessible
# without logging in.
# --- UPDATE YOUR PUBLIC_ENDPOINTS LIST ---
PUBLIC_ENDPOINTS = frozenset({
    'health_check',                   # <--- ADD THIS
    'auth.login',
    'auth.logout',
    'auth.register',
    'auth.access_denied',
    'multicompany.company_login',
    'multicompany.company_register',
    'static',
    'provider_admin.provider_dashboard',
    'provider_admin.provider_login',
    'provider_admin.provider_api_tenants',
    'provider_admin.provider_api_toggle_module',
    'sales.landing',
    'sales.contact',
})

# --- ADD THIS ROUTE ABOVE YOUR index() FUNCTION ---
@app.route('/health')
@csrf.exempt  # Ensure health checks don't require CSRF tokens
def health_check():
    """
    Service health check endpoint for Nginx/AWS ALB.
    Bypasses authentication and license gates.
    """
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'ethiopian-business-logic'
    }), 200

# URL prefixes that are always public (login-related paths).
# This is a safety net in case blueprint names change.
PUBLIC_PREFIXES = ('/auth/login', '/auth/logout', '/auth/register',
                   '/auth/access-denied', '/company/login', '/company/register',
                   '/static/', '/provider/', '/sales/')

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
    if request.path.startswith('/static/') or request.path == '/favicon.ico':
        return None

    # Allow explicitly public endpoints
    endpoint = request.endpoint
    if endpoint and endpoint in PUBLIC_ENDPOINTS:
        return None

    # Safety-net: also match by URL path
    for prefix in PUBLIC_PREFIXES:
        if request.path.startswith(prefix):
            return None

    # If not logged in → redirect to login
    if not session.get('logged_in'):
        flash('Please log in to continue.', 'warning')
        return redirect(url_for('auth.login'))


@app.before_request
def set_company_context():
    """Inject g.company_id for every authenticated request.

    Sources (in priority order):
      1. session['current_company_id'] (set at login or company-switch)
      2. Default tenant from the platform (auto-created on first run)

    Also sets g.tenant with the full tenant record.
    """
    # Skip for unauthenticated / public requests
    if not session.get('logged_in'):
        g.company_id = None
        g.tenant = None
        return None

    company_id = session.get('current_company_id')

    if not company_id:
        # Fall back to default tenant
        company_id = tenant_store.ensure_default_tenant()
        session['current_company_id'] = company_id

    g.company_id = company_id
    g.tenant = tenant_store.get_tenant(company_id)

    # If tenant doesn't exist yet (e.g. legacy data), auto-create it
    if g.tenant is None:
        tenant_store.create_tenant({
            'company_id': company_id,
            'company_name': session.get('company_name', 'My Company'),
            'subscription_tier': 'enterprise',
        }, created_by=session.get('username', 'system'))
        g.tenant = tenant_store.get_tenant(company_id)


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
    """Setup page - create standard chart of accounts"""
    return render_template('setup.html')


@app.route('/setup', methods=['POST'])
def setup_accounts():
    """Process setup of standard accounts"""
    ledger.create_standard_chart_of_accounts()
    flash(f'Successfully created {len(ledger.accounts)} standard accounts!', 'success')
    return redirect(url_for('accounts'))


@app.route('/accounts')
def accounts():
    """View all accounts"""
    accounts_by_type = {}
    for account in ledger.accounts.values():
        acc_type = account.account_type.value
        if acc_type not in accounts_by_type:
            accounts_by_type[acc_type] = []
        accounts_by_type[acc_type].append(account)
    
    # Sort accounts within each type by ID
    for acc_type in accounts_by_type:
        accounts_by_type[acc_type].sort(key=lambda x: x.account_id)
    
    return render_template('accounts.html', accounts_by_type=accounts_by_type)


@app.route('/accounts/new')
def new_account():
    """Form to create new account"""
    return render_template('new_account.html', account_types=AccountType)


@app.route('/accounts/new', methods=['POST'])
def create_account():
    """Create new account"""
    account_id = request.form['account_id'].strip()
    name = request.form['name'].strip()
    account_type = AccountType(request.form['account_type'])
    
    if account_id in ledger.accounts:
        flash('Account ID already exists!', 'error')
        return redirect(url_for('new_account'))
    
    account = Account(account_id, name, account_type)
    
    if ledger.add_account(account):
        flash(f'Account "{name}" created successfully!', 'success')
    else:
        flash('Failed to create account!', 'error')
    
    return redirect(url_for('accounts'))


@app.route('/journal-entry')
def journal_entry_form():
    """Form to create journal entry"""
    return render_template('journal_entry.html', accounts=ledger.accounts)


@app.route('/journal-entry', methods=['POST'])
def create_journal_entry():
    """Create new journal entry"""
    description = request.form['description'].strip()
    reference = request.form.get('reference', '').strip()
    
    entry = JournalEntry(description=description, reference=reference)
    
    # Process entry lines
    account_ids = request.form.getlist('account_id[]')
    debit_amounts = request.form.getlist('debit_amount[]')
    credit_amounts = request.form.getlist('credit_amount[]')
    
    for i, account_id in enumerate(account_ids):
        if account_id and account_id in ledger.accounts:
            debit = float(debit_amounts[i] or 0)
            credit = float(credit_amounts[i] or 0)
            
            if debit > 0 or credit > 0:
                entry.add_line(account_id, debit_amount=debit, credit_amount=credit)
    
    if len(entry.lines) >= 2:
        if entry.validate():
            if ledger.post_journal_entry(entry):
                flash('Journal entry posted successfully!', 'success')
            else:
                flash('Failed to post journal entry!', 'error')
        else:
            flash('Journal entry is not balanced!', 'error')
    else:
        flash('Journal entry must have at least 2 lines!', 'error')
    
    return redirect(url_for('journal_entry_form'))


@app.route('/quick-transactions')
def quick_transactions():
    """Quick transaction templates"""
    return render_template('quick_transactions.html')


@app.route('/quick-sale', methods=['POST'])
def quick_sale():
    """Process quick cash sale"""
    amount = float(request.form['amount'])
    description = request.form['description'].strip()
    
    entry = JournalEntryBuilder.cash_sale("1000", "4000", amount, description)
    
    if ledger.post_journal_entry(entry):
        flash(f'Cash sale of ${amount:,.2f} recorded successfully!', 'success')
    else:
        flash('Failed to record sale. Make sure accounts 1000 and 4000 exist.', 'error')
    
    return redirect(url_for('quick_transactions'))


@app.route('/quick-expense', methods=['POST'])
def quick_expense():
    """Process quick expense"""
    amount = float(request.form['amount'])
    description = request.form['description'].strip()
    expense_account = request.form['expense_account']
    
    entry = JournalEntryBuilder.expense_payment(expense_account, "1000", amount, description)
    
    if ledger.post_journal_entry(entry):
        flash(f'Expense of ${amount:,.2f} recorded successfully!', 'success')
    else:
        flash('Failed to record expense. Check if accounts exist.', 'error')
    
    return redirect(url_for('quick_transactions'))


@app.route('/reports/trial-balance')
def trial_balance():
    """Trial balance report"""
    trial_balance_data = ledger.get_trial_balance()
    
    # Prepare data for template
    accounts_data = []
    total_debits = 0
    total_credits = 0
    
    for account_id, balance in trial_balance_data.items():
        account = ledger.get_account(account_id)
        if balance >= 0:
            total_debits += balance
            accounts_data.append({
                'id': account_id,
                'name': account.name,
                'debit': balance,
                'credit': 0
            })
        else:
            total_credits += -balance
            accounts_data.append({
                'id': account_id,
                'name': account.name,
                'debit': 0,
                'credit': -balance
            })
    
    return render_template('trial_balance.html', 
                         accounts=accounts_data,
                         total_debits=total_debits,
                         total_credits=total_credits,
                         as_of_date=datetime.now().strftime('%B %d, %Y'))


@app.route('/reports/income-statement')
def income_statement():
    """Income statement report"""
    # Default to current year
    now = datetime.now()
    start_date = datetime(now.year, 1, 1)
    end_date = now
    
    # Check if custom dates provided
    if request.args.get('start_date'):
        start_date = datetime.strptime(request.args.get('start_date'), '%Y-%m-%d')
    if request.args.get('end_date'):
        end_date = datetime.strptime(request.args.get('end_date'), '%Y-%m-%d')
    
    income_statement_data = ledger.get_income_statement(start_date, end_date)
    
    return render_template('income_statement.html', 
                         data=income_statement_data,
                         start_date=start_date.strftime('%Y-%m-%d'),
                         end_date=end_date.strftime('%Y-%m-%d'))


@app.route('/reports/balance-sheet')
def balance_sheet():
    """Balance sheet report"""
    as_of_date = datetime.now()
    
    if request.args.get('as_of_date'):
        as_of_date = datetime.strptime(request.args.get('as_of_date'), '%Y-%m-%d')
    
    balance_sheet_data = ledger.get_balance_sheet(as_of_date)
    
    return render_template('balance_sheet.html', 
                         data=balance_sheet_data,
                         as_of_date=as_of_date.strftime('%Y-%m-%d'))


@app.route('/reports/account-ledger/<account_id>')
def account_ledger(account_id):
    """Account ledger report"""
    account = ledger.get_account(account_id)
    if not account:
        flash('Account not found!', 'error')
        return redirect(url_for('accounts'))
    
    ledger_entries = ledger.get_account_ledger(account_id)
    
    return render_template('account_ledger.html', 
                         account=account,
                         ledger_entries=ledger_entries)


@app.route('/export')
def export_data():
    """Export data to JSON"""
    filename = ledger.export_to_json()
    flash(f'Data exported to {filename}', 'success')
    return redirect(url_for('index'))


# API endpoints for dynamic content
@app.route('/api/accounts')
def api_accounts():
    """Get accounts as JSON"""
    accounts_list = []
    for account in ledger.accounts.values():
        accounts_list.append({
            'id': account.account_id,
            'name': account.name,
            'type': account.account_type.value,
            'balance': account.balance
        })
    return jsonify(accounts_list)


if __name__ == '__main__':
    # Create templates directory structure if it doesn't exist
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
    
    logger.info("Starting Accounting Software Web Interface...")
    logger.info("Access the application at: http://localhost:5000")
    debug_mode = os.environ.get('FLASK_DEBUG', '0').lower() in ('1', 'true', 'yes')
    app.run(debug=debug_mode, host='localhost', port=5000)