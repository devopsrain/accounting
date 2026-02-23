"""
Multi-Tenant & Module Licensing Data Store

Persistent parquet-backed management for:
- Company (tenant) registration and metadata
- Subscription tiers with module access control
- Per-company license enforcement
- Provider-level administration

Storage layout:
    data/platform/tenants.parquet      – company/tenant records
    data/platform/licenses.parquet     – per-company module licenses
    data/platform/license_audit.parquet – license change history
"""

import os
import uuid
import logging
import pandas as pd
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'platform')

TENANTS_FILE = os.path.join(DATA_DIR, 'tenants.parquet')
LICENSES_FILE = os.path.join(DATA_DIR, 'licenses.parquet')
LICENSE_AUDIT_FILE = os.path.join(DATA_DIR, 'license_audit.parquet')

# ── Subscription Tiers ────────────────────────────────────────────
# Each tier defines which modules are included by default.
# Provider admins can override per-company.
SUBSCRIPTION_TIERS = {
    'starter': {
        'display_name': 'Starter',
        'max_users': 3,
        'max_employees': 25,
        'price_monthly_etb': 0,
        'modules': [
            'auth', 'accounts', 'journal', 'vat',
        ],
        'description': 'Core accounting — Chart of Accounts, Journal Entries, VAT',
    },
    'professional': {
        'display_name': 'Professional',
        'max_users': 15,
        'max_employees': 200,
        'price_monthly_etb': 2500,
        'modules': [
            'auth', 'accounts', 'journal', 'vat',
            'income_expense', 'transactions', 'cpo', 'employees',
            'payroll',
        ],
        'description': 'Full financial suite — adds Income/Expense, Transactions, CPO, Payroll',
    },
    'enterprise': {
        'display_name': 'Enterprise',
        'max_users': 999999,
        'max_employees': 999999,
        'price_monthly_etb': 7500,
        'modules': [
            'auth', 'accounts', 'journal', 'vat',
            'income_expense', 'transactions', 'cpo', 'employees',
            'payroll', 'inventory', 'bid', 'siem', 'backup',
            'version', 'multicompany',
        ],
        'description': 'Everything — adds Inventory, Bid Tracker, SIEM, Backup, Version Control',
    },
}

# Map Flask blueprint names → module identifiers used in licensing.
# Multiple blueprints can map to the same module.
BLUEPRINT_TO_MODULE: Dict[str, str] = {
    'auth':            'auth',           # always allowed
    'accounts_bp':     'accounts',
    'chart_of_accounts': 'accounts',
    'journal_bp':      'journal',
    'journal':         'journal',
    'vat':             'vat',
    'vat_bp':          'vat',
    'income_expense':  'income_expense',
    'income_expense_bp': 'income_expense',
    'transaction':     'transactions',
    'transaction_bp':  'transactions',
    'transactions':    'transactions',
    'cpo':             'cpo',
    'cpo_bp':          'cpo',
    'payroll':         'payroll',
    'employee':        'employees',
    'employees':       'employees',
    'inventory':       'inventory',
    'inventory_bp':    'inventory',
    'bid':             'bid',
    'bid_bp':          'bid',
    'siem':            'siem',
    'siem_bp':         'siem',
    'backup':          'backup',
    'backup_bp':       'backup',
    'version':         'version',
    'version_bp':      'version',
    'multicompany':    'multicompany',
}

# Modules that are ALWAYS accessible regardless of license
ALWAYS_ALLOWED_MODULES = frozenset({'auth', 'static'})


class TenantDataStore:
    """Manages company tenants, subscriptions, and module licenses."""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._ensure_files()

    # ── File Initialization ───────────────────────────────────────

    def _ensure_files(self):
        """Create parquet files if they don't exist."""
        if not os.path.exists(TENANTS_FILE):
            df = pd.DataFrame(columns=[
                'company_id', 'company_name', 'registration_number',
                'tin_number', 'address', 'city', 'country',
                'phone', 'email', 'business_type',
                'subscription_tier', 'subscription_status',
                'subscription_start', 'subscription_end',
                'max_users', 'max_employees',
                'license_key', 'is_active',
                'created_at', 'updated_at',
                'created_by', 'notes',
            ])
            df.to_parquet(TENANTS_FILE, index=False)
            logger.info("Created tenants store: %s", TENANTS_FILE)

        if not os.path.exists(LICENSES_FILE):
            df = pd.DataFrame(columns=[
                'license_id', 'company_id', 'module_name',
                'is_enabled', 'granted_at', 'expires_at',
                'granted_by', 'notes',
            ])
            df.to_parquet(LICENSES_FILE, index=False)
            logger.info("Created licenses store: %s", LICENSES_FILE)

        if not os.path.exists(LICENSE_AUDIT_FILE):
            df = pd.DataFrame(columns=[
                'audit_id', 'company_id', 'module_name',
                'action', 'performed_by', 'timestamp', 'details',
            ])
            df.to_parquet(LICENSE_AUDIT_FILE, index=False)
            logger.info("Created license audit store: %s", LICENSE_AUDIT_FILE)

    # ── Tenant CRUD ───────────────────────────────────────────────

    def create_tenant(self, company_data: dict, created_by: str = 'system') -> dict:
        """Register a new company tenant.

        Args:
            company_data: dict with company_name, registration_number,
                          tin_number, subscription_tier, etc.
            created_by: username of the provider admin creating the tenant.

        Returns:
            The created tenant record as dict.
        """
        tier_key = company_data.get('subscription_tier', 'starter')
        tier = SUBSCRIPTION_TIERS.get(tier_key, SUBSCRIPTION_TIERS['starter'])

        now = datetime.now().isoformat()
        company_id = company_data.get('company_id') or str(uuid.uuid4())

        record = {
            'company_id': company_id,
            'company_name': company_data.get('company_name', ''),
            'registration_number': company_data.get('registration_number', ''),
            'tin_number': company_data.get('tin_number', ''),
            'address': company_data.get('address', ''),
            'city': company_data.get('city', 'Addis Ababa'),
            'country': company_data.get('country', 'Ethiopia'),
            'phone': company_data.get('phone', ''),
            'email': company_data.get('email', ''),
            'business_type': company_data.get('business_type', ''),
            'subscription_tier': tier_key,
            'subscription_status': 'active',
            'subscription_start': date.today().isoformat(),
            'subscription_end': (date.today() + timedelta(days=365)).isoformat(),
            'max_users': tier['max_users'],
            'max_employees': tier['max_employees'],
            'license_key': str(uuid.uuid4()),
            'is_active': True,
            'created_at': now,
            'updated_at': now,
            'created_by': created_by,
            'notes': company_data.get('notes', ''),
        }

        df = pd.read_parquet(TENANTS_FILE) if os.path.exists(TENANTS_FILE) else pd.DataFrame()
        df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
        df.to_parquet(TENANTS_FILE, index=False)

        # Auto-provision module licenses based on tier
        self._provision_tier_licenses(company_id, tier_key, created_by)

        # Create company data directory
        company_data_dir = os.path.join(
            os.path.dirname(__file__), 'data', 'companies', company_id
        )
        os.makedirs(company_data_dir, exist_ok=True)

        logger.info("Created tenant '%s' (%s) on tier '%s'",
                     record['company_name'], company_id, tier_key)
        return record

    def get_tenant(self, company_id: str) -> Optional[dict]:
        """Get tenant by company_id."""
        if not os.path.exists(TENANTS_FILE):
            return None
        df = pd.read_parquet(TENANTS_FILE)
        match = df[df['company_id'] == company_id]
        if match.empty:
            return None
        return match.iloc[0].to_dict()

    def get_tenant_by_license_key(self, license_key: str) -> Optional[dict]:
        """Look up a tenant by its license key."""
        if not os.path.exists(TENANTS_FILE):
            return None
        df = pd.read_parquet(TENANTS_FILE)
        match = df[df['license_key'] == license_key]
        if match.empty:
            return None
        return match.iloc[0].to_dict()

    def get_all_tenants(self) -> List[dict]:
        """Return all registered tenants."""
        if not os.path.exists(TENANTS_FILE):
            return []
        df = pd.read_parquet(TENANTS_FILE)
        if df.empty:
            return []
        return df.to_dict('records')

    def update_tenant(self, company_id: str, updates: dict) -> bool:
        """Update tenant fields."""
        if not os.path.exists(TENANTS_FILE):
            return False
        df = pd.read_parquet(TENANTS_FILE)
        mask = df['company_id'] == company_id
        if not mask.any():
            return False
        for key, value in updates.items():
            if key in df.columns and key != 'company_id':
                df.loc[mask, key] = value
        df.loc[mask, 'updated_at'] = datetime.now().isoformat()
        df.to_parquet(TENANTS_FILE, index=False)
        return True

    def suspend_tenant(self, company_id: str, reason: str = '') -> bool:
        """Suspend a tenant — blocks all module access."""
        return self.update_tenant(company_id, {
            'subscription_status': 'suspended',
            'is_active': False,
            'notes': f'Suspended: {reason}',
        })

    def reactivate_tenant(self, company_id: str) -> bool:
        """Re-activate a suspended tenant."""
        return self.update_tenant(company_id, {
            'subscription_status': 'active',
            'is_active': True,
        })

    def delete_tenant(self, company_id: str) -> bool:
        """Soft-delete tenant (marks inactive, keeps data)."""
        return self.update_tenant(company_id, {
            'subscription_status': 'deleted',
            'is_active': False,
        })

    # ── Subscription Management ───────────────────────────────────

    def change_subscription_tier(self, company_id: str, new_tier: str,
                                  changed_by: str = 'system') -> bool:
        """Upgrade or downgrade a tenants subscription tier."""
        if new_tier not in SUBSCRIPTION_TIERS:
            return False

        tier = SUBSCRIPTION_TIERS[new_tier]
        success = self.update_tenant(company_id, {
            'subscription_tier': new_tier,
            'max_users': tier['max_users'],
            'max_employees': tier['max_employees'],
        })
        if success:
            # Re-provision licenses for the new tier
            self._provision_tier_licenses(company_id, new_tier, changed_by)
            self._audit_log(company_id, '*', 'tier_change',
                            changed_by, f'Changed to {new_tier}')
        return success

    def is_subscription_active(self, company_id: str) -> bool:
        """Check if a tenant's subscription is active and not expired."""
        tenant = self.get_tenant(company_id)
        if not tenant:
            return False
        if tenant.get('subscription_status') != 'active':
            return False
        if not tenant.get('is_active'):
            return False
        end_str = tenant.get('subscription_end', '')
        if end_str:
            try:
                end_date = date.fromisoformat(str(end_str).split('T')[0])
                if end_date < date.today():
                    return False
            except (ValueError, TypeError):
                pass
        return True

    # ── Module Licensing ──────────────────────────────────────────

    def _provision_tier_licenses(self, company_id: str, tier_key: str,
                                  granted_by: str = 'system'):
        """Create/update module licenses based on subscription tier."""
        tier = SUBSCRIPTION_TIERS.get(tier_key, SUBSCRIPTION_TIERS['starter'])
        tier_modules = set(tier['modules'])

        df = pd.read_parquet(LICENSES_FILE) if os.path.exists(LICENSES_FILE) else pd.DataFrame()
        existing = df[df['company_id'] == company_id] if not df.empty else pd.DataFrame()

        now = datetime.now().isoformat()
        new_rows = []

        for module in tier_modules:
            if existing.empty or not (existing['module_name'] == module).any():
                new_rows.append({
                    'license_id': str(uuid.uuid4()),
                    'company_id': company_id,
                    'module_name': module,
                    'is_enabled': True,
                    'granted_at': now,
                    'expires_at': '',
                    'granted_by': granted_by,
                    'notes': f'Auto-provisioned with {tier_key} tier',
                })
            else:
                # Re-enable if it was disabled during a downgrade
                mask = (df['company_id'] == company_id) & (df['module_name'] == module)
                df.loc[mask, 'is_enabled'] = True

        # Disable modules NOT in the new tier (downgrade scenario)
        if not existing.empty:
            for _, row in existing.iterrows():
                if row['module_name'] not in tier_modules:
                    mask = (df['company_id'] == company_id) & \
                           (df['module_name'] == row['module_name'])
                    df.loc[mask, 'is_enabled'] = False

        if new_rows:
            df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)

        df.to_parquet(LICENSES_FILE, index=False)

    def get_company_licenses(self, company_id: str) -> List[dict]:
        """Get all module licenses for a company."""
        if not os.path.exists(LICENSES_FILE):
            return []
        df = pd.read_parquet(LICENSES_FILE)
        if df.empty:
            return []
        filtered = df[df['company_id'] == company_id]
        return filtered.to_dict('records')

    def get_enabled_modules(self, company_id: str) -> set:
        """Return set of module names this company can access."""
        licenses = self.get_company_licenses(company_id)
        return {lic['module_name'] for lic in licenses if lic.get('is_enabled')}

    def is_module_licensed(self, company_id: str, module_name: str) -> bool:
        """Check if a specific module is licensed for this company."""
        if module_name in ALWAYS_ALLOWED_MODULES:
            return True
        enabled = self.get_enabled_modules(company_id)
        return module_name in enabled

    def toggle_module(self, company_id: str, module_name: str,
                      enable: bool, changed_by: str = 'system') -> bool:
        """Enable or disable a single module for a company."""
        if not os.path.exists(LICENSES_FILE):
            return False
        df = pd.read_parquet(LICENSES_FILE)
        mask = (df['company_id'] == company_id) & (df['module_name'] == module_name)

        if not mask.any():
            # Create new license row
            new_row = {
                'license_id': str(uuid.uuid4()),
                'company_id': company_id,
                'module_name': module_name,
                'is_enabled': enable,
                'granted_at': datetime.now().isoformat(),
                'expires_at': '',
                'granted_by': changed_by,
                'notes': f'Manually {"enabled" if enable else "disabled"}',
            }
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        else:
            df.loc[mask, 'is_enabled'] = enable

        df.to_parquet(LICENSES_FILE, index=False)
        action = 'module_enabled' if enable else 'module_disabled'
        self._audit_log(company_id, module_name, action, changed_by, '')
        return True

    # ── Audit Log ─────────────────────────────────────────────────

    def _audit_log(self, company_id: str, module_name: str,
                   action: str, performed_by: str, details: str):
        """Append an entry to the license audit trail."""
        row = {
            'audit_id': str(uuid.uuid4()),
            'company_id': company_id,
            'module_name': module_name,
            'action': action,
            'performed_by': performed_by,
            'timestamp': datetime.now().isoformat(),
            'details': details,
        }
        df = pd.read_parquet(LICENSE_AUDIT_FILE) \
            if os.path.exists(LICENSE_AUDIT_FILE) else pd.DataFrame()
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        df.to_parquet(LICENSE_AUDIT_FILE, index=False)

    def get_audit_log(self, company_id: Optional[str] = None,
                      limit: int = 100) -> List[dict]:
        """Return license audit log, optionally filtered by company."""
        if not os.path.exists(LICENSE_AUDIT_FILE):
            return []
        df = pd.read_parquet(LICENSE_AUDIT_FILE)
        if df.empty:
            return []
        if company_id:
            df = df[df['company_id'] == company_id]
        df = df.sort_values('timestamp', ascending=False).head(limit)
        return df.to_dict('records')

    # ── Provider Statistics ───────────────────────────────────────

    def get_platform_stats(self) -> dict:
        """Return platform-wide statistics for the provider dashboard."""
        tenants = self.get_all_tenants()
        active = [t for t in tenants if t.get('is_active')]
        by_tier = {}
        for t in active:
            tier = t.get('subscription_tier', 'starter')
            by_tier[tier] = by_tier.get(tier, 0) + 1

        return {
            'total_tenants': len(tenants),
            'active_tenants': len(active),
            'suspended_tenants': len([t for t in tenants
                                      if t.get('subscription_status') == 'suspended']),
            'tenants_by_tier': by_tier,
            'tiers_available': SUBSCRIPTION_TIERS,
        }

    # ── Default Tenant Seeder ─────────────────────────────────────

    def ensure_default_tenant(self) -> str:
        """Ensure at least one tenant exists for single-company mode.

        Returns the default company_id.
        """
        tenants = self.get_all_tenants()
        if tenants:
            # Return first active tenant
            for t in tenants:
                if t.get('is_active'):
                    return t['company_id']
            # All inactive — return first anyway
            return tenants[0]['company_id']

        # No tenants — create the default one
        record = self.create_tenant({
            'company_id': 'default',
            'company_name': 'Default Company',
            'registration_number': 'REG-0001',
            'tin_number': 'TIN-0001',
            'subscription_tier': 'enterprise',
        }, created_by='system')
        logger.info("Created default tenant (enterprise tier)")
        return record['company_id']


# Module-level singleton
tenant_store = TenantDataStore()
