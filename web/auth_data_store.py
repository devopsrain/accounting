"""
User Authentication & Authorization Data Store

Persistent parquet-backed user management with:
- Username/password authentication (SHA-256, upgradeable)
- Role-based privilege levels
- Login history tracking
- Session management helpers
- SIEM integration (auto-logs auth events)
"""

import pandas as pd
import uuid
import os
import hashlib
import logging
import bcrypt
from datetime import datetime
from flask import session, request, redirect, url_for, flash
from functools import wraps

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'auth')
USERS_FILE = os.path.join(DATA_DIR, 'users.parquet')
LOGIN_HISTORY_FILE = os.path.join(DATA_DIR, 'login_history.parquet')

# ── Security Constants ──────────────────────────────────────────
MAX_FAILED_LOGIN_ATTEMPTS = 5      # lock account after N failures
ACCOUNT_LOCKOUT_MINUTES = 30       # how long the account stays locked
MIN_PASSWORD_LENGTH = 4            # minimum password characters

# ── Privilege Levels ──────────────────────────────────────────────
# Higher number = more privileges
PRIVILEGE_LEVELS = {
    'viewer':       10,   # Read-only access
    'data_entry':   20,   # Can enter data (add records)
    'operator':     30,   # Can import/export, run reports
    'manager':      40,   # Can manage employees, approve
    'admin':        50,   # Full access to a module
    'super_admin':  99,   # Full access to everything
}

PRIVILEGE_DESCRIPTIONS = {
    'viewer':       'View dashboards and reports only',
    'data_entry':   'Add and edit records',
    'operator':     'Import/export data, run reports',
    'manager':      'Manage employees, approve actions',
    'admin':        'Full module access',
    'super_admin':  'Full system access',
}

# Module permission requirements
MODULE_MIN_PRIVILEGE = {
    'vat':            'data_entry',
    'payroll':        'operator',
    'accounts':       'data_entry',
    'journal':        'data_entry',
    'income_expense': 'data_entry',
    'transaction':    'operator',
    'cpo':            'operator',
    'inventory':      'operator',
    'multicompany':   'viewer',
    'siem':           'admin',     # Only admins can view security logs
}


def _hash_password(password: str) -> str:
    """Hash password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify password against stored hash.

    Supports both bcrypt (new) and legacy SHA-256 hashes.
    If a legacy hash matches, return True so the caller can
    transparently re-hash with bcrypt.
    """
    # Try bcrypt first (hashes start with '$2b$')
    if password_hash.startswith('$2b$') or password_hash.startswith('$2a$'):
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    # Fall back to legacy SHA-256 for migration
    return hashlib.sha256(password.encode()).hexdigest() == password_hash


def _is_legacy_hash(password_hash: str) -> bool:
    """Check if the hash is a legacy SHA-256 that should be upgraded."""
    return not (password_hash.startswith('$2b$') or password_hash.startswith('$2a$'))


class AuthDataStore:
    """Persistent user authentication and authorization store."""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._ensure_default_users()

    # ── User CRUD ─────────────────────────────────────────────────

    def _load_users(self) -> pd.DataFrame:
        if os.path.exists(USERS_FILE):
            return pd.read_parquet(USERS_FILE)
        return pd.DataFrame()

    def _save_users(self, df: pd.DataFrame):
        df.to_parquet(USERS_FILE, index=False)

    def _ensure_default_users(self):
        """Create default admin user if no users exist."""
        if os.path.exists(USERS_FILE):
            df = pd.read_parquet(USERS_FILE)
            if len(df) > 0:
                return

        import secrets

        def _default_pw(env_var: str, fallback_length: int = 16) -> str:
            """Return password from env var, or generate a secure random one."""
            return os.environ.get(env_var) or secrets.token_urlsafe(fallback_length)

        admin_pw     = _default_pw('DEFAULT_ADMIN_PASSWORD')
        hr_pw        = _default_pw('DEFAULT_HR_PASSWORD')
        accountant_pw = _default_pw('DEFAULT_ACCOUNTANT_PASSWORD')
        employee_pw  = _default_pw('DEFAULT_EMPLOYEE_PASSWORD')
        data_pw      = _default_pw('DEFAULT_DATA_ENTRY_PASSWORD')

        default_users = [
            {
                'user_id': str(uuid.uuid4()),
                'username': 'admin',
                'password_hash': _hash_password(admin_pw),
                'full_name': 'System Administrator',
                'email': 'admin@system.et',
                'phone': '+251-11-999-0001',
                'privilege_level': 'super_admin',
                'is_active': True,
                'created_at': datetime.now().isoformat(),
                'last_login': '',
                'login_count': 0,
                'failed_login_count': 0,
                'locked_until': '',
            },
            {
                'user_id': str(uuid.uuid4()),
                'username': 'hr_manager',
                'password_hash': _hash_password(hr_pw),
                'full_name': 'Almaz Tadesse',
                'email': 'hr.manager@addistech.et',
                'phone': '+251-11-555-1001',
                'privilege_level': 'manager',
                'is_active': True,
                'created_at': datetime.now().isoformat(),
                'last_login': '',
                'login_count': 0,
                'failed_login_count': 0,
                'locked_until': '',
            },
            {
                'user_id': str(uuid.uuid4()),
                'username': 'accountant',
                'password_hash': _hash_password(accountant_pw),
                'full_name': 'Dawit Mengistu',
                'email': 'accountant@addistech.et',
                'phone': '+251-11-555-1002',
                'privilege_level': 'operator',
                'is_active': True,
                'created_at': datetime.now().isoformat(),
                'last_login': '',
                'login_count': 0,
                'failed_login_count': 0,
                'locked_until': '',
            },
            {
                'user_id': str(uuid.uuid4()),
                'username': 'employee1',
                'password_hash': _hash_password(employee_pw),
                'full_name': 'Meron Haile',
                'email': 'employee1@addistech.et',
                'phone': '+251-11-555-2001',
                'privilege_level': 'viewer',
                'is_active': True,
                'created_at': datetime.now().isoformat(),
                'last_login': '',
                'login_count': 0,
                'failed_login_count': 0,
                'locked_until': '',
            },
            {
                'user_id': str(uuid.uuid4()),
                'username': 'data_entry',
                'password_hash': _hash_password(data_pw),
                'full_name': 'Hanan Ahmed',
                'email': 'data@addistech.et',
                'phone': '+251-11-555-3001',
                'privilege_level': 'data_entry',
                'is_active': True,
                'created_at': datetime.now().isoformat(),
                'last_login': '',
                'login_count': 0,
                'failed_login_count': 0,
                'locked_until': '',
            },
        ]
        df = pd.DataFrame(default_users)
        self._save_users(df)

        # Log generated credentials so the admin can capture them on first run
        logger.warning('=== DEFAULT CREDENTIALS (first run) ===')
        logger.warning('  admin      : %s', admin_pw)
        logger.warning('  hr_manager : %s', hr_pw)
        logger.warning('  accountant : %s', accountant_pw)
        logger.warning('  employee1  : %s', employee_pw)
        logger.warning('  data_entry : %s', data_pw)
        logger.warning('Change these immediately or set DEFAULT_*_PASSWORD env vars.')
        logger.warning('=======================================')

    def authenticate(self, username: str, password: str) -> dict:
        """
        Authenticate user by username/email and password.
        Returns user dict on success, None on failure.
        Also logs the attempt to SIEM.
        """
        df = self._load_users()
        if df.empty:
            return None

        # Find user by username or email
        mask = (df['username'] == username) | (df['email'] == username)
        matches = df[mask]

        if matches.empty:
            self._log_auth_event(username, success=False, reason='User not found')
            return None

        user = matches.iloc[0].to_dict()

        # Check if account is locked
        if user.get('locked_until') and user['locked_until']:
            try:
                locked_until = datetime.fromisoformat(user['locked_until'])
                if datetime.now() < locked_until:
                    self._log_auth_event(username, success=False, reason='Account locked')
                    return None
                else:
                    # Unlock — reset failed count
                    idx = df.index[mask][0]
                    df.at[idx, 'locked_until'] = ''
                    df.at[idx, 'failed_login_count'] = 0
                    self._save_users(df)
            except (ValueError, TypeError):
                pass

        # Check if active
        if not user.get('is_active', True):
            self._log_auth_event(username, success=False, reason='Account disabled')
            return None

        # Verify password
        if not _verify_password(password, user['password_hash']):
            # Increment failed count
            idx = df.index[mask][0]
            failed = int(df.at[idx, 'failed_login_count'] or 0) + 1
            df.at[idx, 'failed_login_count'] = failed

            # Lock after N failed attempts
            if failed >= MAX_FAILED_LOGIN_ATTEMPTS:
                from datetime import timedelta
                df.at[idx, 'locked_until'] = (datetime.now() + timedelta(minutes=ACCOUNT_LOCKOUT_MINUTES)).isoformat()

            self._save_users(df)
            self._log_auth_event(username, success=False, reason='Invalid password')
            return None

        # Transparently upgrade legacy SHA-256 hashes to bcrypt
        if _is_legacy_hash(user['password_hash']):
            idx = df.index[mask][0]
            df.at[idx, 'password_hash'] = _hash_password(password)
            self._save_users(df)
            logger.info("Upgraded password hash to bcrypt for user '%s'", username)

        # Success — update stats
        idx = df.index[mask][0]
        df.at[idx, 'last_login'] = datetime.now().isoformat()
        df.at[idx, 'login_count'] = int(df.at[idx, 'login_count'] or 0) + 1
        df.at[idx, 'failed_login_count'] = 0
        df.at[idx, 'locked_until'] = ''
        self._save_users(df)

        self._log_auth_event(username, success=True)
        self._log_login_history(user)

        return user

    def _log_auth_event(self, username: str, success: bool, reason: str = ''):
        """Log authentication event to SIEM."""
        try:
            from siem_data_store import siem_store
            from flask import request as flask_request
            siem_store.log_upload_event(
                flask_request,
                module='auth',
                endpoint='/auth/login',
                filename='',
                status='success' if success else 'failed',
                user=username,
                details=f"Login {'successful' if success else 'failed'}: {reason}" if reason else f"Login {'successful' if success else 'failed'}"
            )
        except Exception as e:
            logger.warning("SIEM logging failed during auth event: %s", e)  # Don't break auth if SIEM is down

    def _log_login_history(self, user: dict):
        """Log login to persistent history."""
        try:
            from flask import request as flask_request
            ip = (
                flask_request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
                or flask_request.headers.get('X-Real-IP', '')
                or flask_request.remote_addr
                or 'unknown'
            )
        except Exception as e:
            logger.debug("Could not extract IP from request: %s", e)
            ip = 'unknown'

        entry = {
            'login_id': str(uuid.uuid4()),
            'user_id': user['user_id'],
            'username': user['username'],
            'timestamp': datetime.now().isoformat(),
            'ip_address': ip,
            'user_agent': '',
        }
        try:
            from flask import request as flask_request
            entry['user_agent'] = flask_request.headers.get('User-Agent', '')
        except Exception as e:
            logger.debug("Could not extract User-Agent from request: %s", e)

        new_df = pd.DataFrame([entry])
        if os.path.exists(LOGIN_HISTORY_FILE):
            existing = pd.read_parquet(LOGIN_HISTORY_FILE)
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df
        combined.to_parquet(LOGIN_HISTORY_FILE, index=False)

    # ── Session Helpers ───────────────────────────────────────────

    def set_session(self, user: dict):
        """Set Flask session after successful authentication."""
        session['user_id'] = user['user_id']
        session['username'] = user['username']
        session['full_name'] = user.get('full_name', user['username'])
        session['privilege_level'] = user.get('privilege_level', 'viewer')
        session['logged_in'] = True

    def clear_session(self):
        """Clear Flask session on logout."""
        session.clear()

    def get_current_user(self) -> dict:
        """Get currently logged-in user from session."""
        if not session.get('logged_in'):
            return None
        return {
            'user_id': session.get('user_id'),
            'username': session.get('username'),
            'full_name': session.get('full_name'),
            'privilege_level': session.get('privilege_level', 'viewer'),
        }

    def get_current_username(self) -> str:
        """Get current username or 'anonymous'."""
        return session.get('username', 'anonymous')

    # ── Privilege Checks ──────────────────────────────────────────

    def has_privilege(self, required_level: str) -> bool:
        """Check if current session user meets the required privilege level."""
        user_level = session.get('privilege_level', 'viewer')
        return PRIVILEGE_LEVELS.get(user_level, 0) >= PRIVILEGE_LEVELS.get(required_level, 0)

    def can_access_module(self, module: str) -> bool:
        """Check if current session user can access a module."""
        required = MODULE_MIN_PRIVILEGE.get(module, 'viewer')
        return self.has_privilege(required)

    # ── User Management (Admin) ───────────────────────────────────

    def get_all_users(self) -> list:
        """Get all users (without password hashes)."""
        df = self._load_users()
        if df.empty:
            return []
        safe = df.drop(columns=['password_hash'], errors='ignore')
        return safe.sort_values('username').to_dict('records')

    def get_user_by_id(self, user_id: str) -> dict:
        """Get a single user by ID."""
        df = self._load_users()
        if df.empty:
            return None
        matches = df[df['user_id'] == user_id]
        if matches.empty:
            return None
        user = matches.iloc[0].to_dict()
        user.pop('password_hash', None)
        return user

    def create_user(self, username: str, password: str, full_name: str,
                    email: str, phone: str = '', privilege_level: str = 'viewer') -> dict:
        """Create a new user."""
        df = self._load_users()

        # Check uniqueness
        if not df.empty:
            if username in df['username'].values:
                return {'success': False, 'error': 'Username already exists'}
            if email and email in df['email'].values:
                return {'success': False, 'error': 'Email already exists'}

        user = {
            'user_id': str(uuid.uuid4()),
            'username': username,
            'password_hash': _hash_password(password),
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'privilege_level': privilege_level,
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'last_login': '',
            'login_count': 0,
            'failed_login_count': 0,
            'locked_until': '',
        }

        new_df = pd.DataFrame([user])
        if df.empty:
            combined = new_df
        else:
            combined = pd.concat([df, new_df], ignore_index=True)
        self._save_users(combined)

        return {'success': True, 'user_id': user['user_id']}

    def update_user(self, user_id: str, **kwargs) -> bool:
        """Update user fields (except password — use change_password)."""
        df = self._load_users()
        if df.empty:
            return False
        mask = df['user_id'] == user_id
        if not mask.any():
            return False

        for key, value in kwargs.items():
            if key in df.columns and key not in ('user_id', 'password_hash'):
                df.loc[mask, key] = value

        self._save_users(df)
        return True

    def change_password(self, user_id: str, new_password: str) -> bool:
        """Change user's password."""
        df = self._load_users()
        if df.empty:
            return False
        mask = df['user_id'] == user_id
        if not mask.any():
            return False

        df.loc[mask, 'password_hash'] = _hash_password(new_password)
        df.loc[mask, 'failed_login_count'] = 0
        df.loc[mask, 'locked_until'] = ''
        self._save_users(df)
        return True

    def toggle_user_active(self, user_id: str) -> bool:
        """Toggle user active/inactive."""
        df = self._load_users()
        if df.empty:
            return False
        mask = df['user_id'] == user_id
        if not mask.any():
            return False

        current = df.loc[mask, 'is_active'].values[0]
        df.loc[mask, 'is_active'] = not current
        self._save_users(df)
        return True

    def delete_user(self, user_id: str) -> bool:
        """Delete a user."""
        df = self._load_users()
        if df.empty:
            return False
        mask = df['user_id'] == user_id
        if not mask.any():
            return False
        df = df[~mask]
        self._save_users(df)
        return True

    # ── Login History ─────────────────────────────────────────────

    def get_login_history(self, limit: int = 100) -> list:
        """Get login history, most recent first."""
        if not os.path.exists(LOGIN_HISTORY_FILE):
            return []
        df = pd.read_parquet(LOGIN_HISTORY_FILE)
        df = df.sort_values('timestamp', ascending=False)
        if limit:
            df = df.head(limit)
        return df.to_dict('records')

    def get_user_login_history(self, user_id: str, limit: int = 50) -> list:
        """Get login history for a specific user."""
        if not os.path.exists(LOGIN_HISTORY_FILE):
            return []
        df = pd.read_parquet(LOGIN_HISTORY_FILE)
        df = df[df['user_id'] == user_id]
        df = df.sort_values('timestamp', ascending=False)
        if limit:
            df = df.head(limit)
        return df.to_dict('records')

    # ── Statistics ────────────────────────────────────────────────

    def get_auth_stats(self) -> dict:
        """Get authentication statistics."""
        df = self._load_users()
        if df.empty:
            return {
                'total_users': 0, 'active_users': 0, 'locked_users': 0,
                'privilege_breakdown': {}, 'recent_logins': 0,
            }

        total = len(df)
        active = len(df[df['is_active'] == True])
        locked = 0
        now = datetime.now()
        for _, row in df.iterrows():
            if row.get('locked_until') and row['locked_until']:
                try:
                    if datetime.fromisoformat(row['locked_until']) > now:
                        locked += 1
                except (ValueError, TypeError):
                    pass

        # Privilege breakdown
        priv = df['privilege_level'].value_counts().to_dict() if 'privilege_level' in df.columns else {}

        # Recent logins (last 24h)
        recent = 0
        if os.path.exists(LOGIN_HISTORY_FILE):
            hist = pd.read_parquet(LOGIN_HISTORY_FILE)
            hist['ts'] = pd.to_datetime(hist['timestamp'])
            recent = len(hist[hist['ts'] >= (now - pd.Timedelta(hours=24))])

        return {
            'total_users': total,
            'active_users': active,
            'locked_users': locked,
            'privilege_breakdown': priv,
            'recent_logins': recent,
            # Flat privilege counts for infographic charts
            'privilege_viewer': priv.get('viewer', 0),
            'privilege_data_entry': priv.get('data_entry', 0),
            'privilege_operator': priv.get('operator', 0),
            'privilege_manager': priv.get('manager', 0),
            'privilege_admin': priv.get('admin', 0),
            'privilege_super_admin': priv.get('super_admin', 0),
        }


# ── Decorator ─────────────────────────────────────────────────────

def login_required(f=None, min_privilege='viewer'):
    """
    Decorator to require authentication and optionally a minimum privilege level.

    Usage:
        @login_required                         # any logged-in user
        @login_required(min_privilege='admin')   # admin+ only
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not session.get('logged_in'):
                flash('Please log in to continue.', 'warning')
                return redirect(url_for('auth.login'))

            if min_privilege != 'viewer':
                user_level = session.get('privilege_level', 'viewer')
                if PRIVILEGE_LEVELS.get(user_level, 0) < PRIVILEGE_LEVELS.get(min_privilege, 0):
                    flash(f'Access denied. Requires {min_privilege} privilege or higher.', 'error')
                    return redirect(url_for('auth.access_denied'))

            return func(*args, **kwargs)
        return wrapper

    if f is not None:
        # Called as @login_required without arguments
        return decorator(f)
    return decorator


# Singleton instance
auth_store = AuthDataStore()

__all__ = [
    'auth_store',
    'login_required',
    'AuthDataStore',
    'PRIVILEGE_LEVELS',
    'PRIVILEGE_DESCRIPTIONS',
    'MODULE_MIN_PRIVILEGE',
    'MAX_FAILED_LOGIN_ATTEMPTS',
    'ACCOUNT_LOCKOUT_MINUTES',
    'MIN_PASSWORD_LENGTH',
]
