-- ============================================================
-- Ethiopian Business Management System - PostgreSQL Schema
-- Run once against your RDS instance to prepare all tables.
-- Safe to re-run: all statements use CREATE TABLE IF NOT EXISTS.
-- ============================================================

-- Enable UUID extension (available on RDS PostgreSQL by default)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ──────────────────────────────────────────────────────────────
-- AUTH MODULE
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    user_id          TEXT PRIMARY KEY,
    username         TEXT NOT NULL UNIQUE,
    password_hash    TEXT NOT NULL,
    full_name        TEXT NOT NULL DEFAULT '',
    email            TEXT NOT NULL DEFAULT '',
    phone            TEXT NOT NULL DEFAULT '',
    privilege_level  TEXT NOT NULL DEFAULT 'viewer',
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TEXT NOT NULL DEFAULT '',
    last_login       TEXT NOT NULL DEFAULT '',
    login_count      INTEGER NOT NULL DEFAULT 0,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS login_history (
    login_id    TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    username    TEXT NOT NULL DEFAULT '',
    timestamp   TEXT NOT NULL DEFAULT '',
    ip_address  TEXT NOT NULL DEFAULT '',
    user_agent  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_login_history_user_id  ON login_history(user_id);
CREATE INDEX IF NOT EXISTS idx_login_history_timestamp ON login_history(timestamp);

-- ──────────────────────────────────────────────────────────────
-- TENANT / MULTI-COMPANY MODULE
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tenants (
    company_id          TEXT PRIMARY KEY,
    company_name        TEXT NOT NULL DEFAULT '',
    registration_number TEXT NOT NULL DEFAULT '',
    tin_number          TEXT NOT NULL DEFAULT '',
    address             TEXT NOT NULL DEFAULT '',
    city                TEXT NOT NULL DEFAULT '',
    country             TEXT NOT NULL DEFAULT 'Ethiopia',
    phone               TEXT NOT NULL DEFAULT '',
    email               TEXT NOT NULL DEFAULT '',
    business_type       TEXT NOT NULL DEFAULT '',
    subscription_tier   TEXT NOT NULL DEFAULT 'basic',
    subscription_status TEXT NOT NULL DEFAULT 'active',
    subscription_start  TEXT NOT NULL DEFAULT '',
    subscription_end    TEXT NOT NULL DEFAULT '',
    max_users           INTEGER NOT NULL DEFAULT 5,
    max_employees       INTEGER NOT NULL DEFAULT 50,
    license_key         TEXT NOT NULL DEFAULT '',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TEXT NOT NULL DEFAULT '',
    updated_at          TEXT NOT NULL DEFAULT '',
    created_by          TEXT NOT NULL DEFAULT '',
    notes               TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS licenses (
    license_id   TEXT PRIMARY KEY,
    company_id   TEXT NOT NULL,
    module_name  TEXT NOT NULL,
    is_enabled   BOOLEAN NOT NULL DEFAULT TRUE,
    granted_at   TEXT NOT NULL DEFAULT '',
    expires_at   TEXT NOT NULL DEFAULT '',
    granted_by   TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_licenses_company_id ON licenses(company_id);

CREATE TABLE IF NOT EXISTS license_audit (
    audit_id     TEXT PRIMARY KEY,
    company_id   TEXT NOT NULL,
    module_name  TEXT NOT NULL DEFAULT '',
    action       TEXT NOT NULL DEFAULT '',
    performed_by TEXT NOT NULL DEFAULT '',
    timestamp    TEXT NOT NULL DEFAULT '',
    details      TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_license_audit_company_id ON license_audit(company_id);

-- ──────────────────────────────────────────────────────────────
-- VAT MODULE
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS vat_income (
    income_id       TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL,
    contract_date   DATE,
    description     TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT '',
    gross_amount    DOUBLE PRECISION NOT NULL DEFAULT 0,
    vat_type        TEXT NOT NULL DEFAULT '',
    vat_rate        DOUBLE PRECISION NOT NULL DEFAULT 0,
    vat_amount      DOUBLE PRECISION NOT NULL DEFAULT 0,
    net_amount      DOUBLE PRECISION NOT NULL DEFAULT 0,
    customer_name   TEXT NOT NULL DEFAULT '',
    customer_tin    TEXT NOT NULL DEFAULT '',
    invoice_number  TEXT NOT NULL DEFAULT '',
    created_date    TIMESTAMP,
    updated_date    TIMESTAMP,
    created_by      TEXT NOT NULL DEFAULT '',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_vat_income_company_id ON vat_income(company_id);
CREATE INDEX IF NOT EXISTS idx_vat_income_contract_date ON vat_income(contract_date);

CREATE TABLE IF NOT EXISTS vat_expenses (
    expense_id      TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL,
    expense_date    DATE,
    description     TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT '',
    gross_amount    DOUBLE PRECISION NOT NULL DEFAULT 0,
    vat_type        TEXT NOT NULL DEFAULT '',
    vat_rate        DOUBLE PRECISION NOT NULL DEFAULT 0,
    vat_amount      DOUBLE PRECISION NOT NULL DEFAULT 0,
    net_amount      DOUBLE PRECISION NOT NULL DEFAULT 0,
    supplier_name   TEXT NOT NULL DEFAULT '',
    supplier_tin    TEXT NOT NULL DEFAULT '',
    receipt_number  TEXT NOT NULL DEFAULT '',
    created_date    TIMESTAMP,
    updated_date    TIMESTAMP,
    created_by      TEXT NOT NULL DEFAULT '',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_vat_expenses_company_id ON vat_expenses(company_id);

CREATE TABLE IF NOT EXISTS vat_capital (
    capital_id      TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL,
    investment_date DATE,
    description     TEXT NOT NULL DEFAULT '',
    capital_type    TEXT NOT NULL DEFAULT '',
    amount          DOUBLE PRECISION NOT NULL DEFAULT 0,
    vat_type        TEXT NOT NULL DEFAULT '',
    vat_rate        DOUBLE PRECISION NOT NULL DEFAULT 0,
    vat_amount      DOUBLE PRECISION NOT NULL DEFAULT 0,
    investor_name   TEXT NOT NULL DEFAULT '',
    investor_tin    TEXT NOT NULL DEFAULT '',
    created_date    TIMESTAMP,
    updated_date    TIMESTAMP,
    created_by      TEXT NOT NULL DEFAULT '',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_vat_capital_company_id ON vat_capital(company_id);

-- ──────────────────────────────────────────────────────────────
-- JOURNAL ENTRIES MODULE
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS journal_entries (
    entry_id         TEXT PRIMARY KEY,
    company_id       TEXT NOT NULL,
    entry_date       TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT '',
    reference_number TEXT NOT NULL DEFAULT '',
    total_debit      DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_credit     DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_by       TEXT NOT NULL DEFAULT '',
    created_date     TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'posted',
    is_active        BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_journal_entries_company_id ON journal_entries(company_id);
CREATE INDEX IF NOT EXISTS idx_journal_entries_entry_date ON journal_entries(entry_date);

CREATE TABLE IF NOT EXISTS journal_entry_lines (
    line_id        TEXT PRIMARY KEY,
    entry_id       TEXT NOT NULL,
    account_code   TEXT NOT NULL DEFAULT '',
    account_name   TEXT NOT NULL DEFAULT '',
    description    TEXT NOT NULL DEFAULT '',
    debit_amount   DOUBLE PRECISION NOT NULL DEFAULT 0,
    credit_amount  DOUBLE PRECISION NOT NULL DEFAULT 0,
    line_number    INTEGER NOT NULL DEFAULT 1,
    created_date   TEXT NOT NULL DEFAULT '',
    is_active      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_jel_entry_id ON journal_entry_lines(entry_id);

-- ──────────────────────────────────────────────────────────────
-- CHART OF ACCOUNTS MODULE
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS chart_of_accounts (
    account_code    TEXT NOT NULL,
    company_id      TEXT NOT NULL,
    account_name    TEXT NOT NULL DEFAULT '',
    account_type    TEXT NOT NULL DEFAULT '',
    account_subtype TEXT NOT NULL DEFAULT '',
    parent_account  TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    normal_balance  TEXT NOT NULL DEFAULT '',
    current_balance DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_date    TEXT NOT NULL DEFAULT '',
    modified_date   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (account_code, company_id)
);

CREATE INDEX IF NOT EXISTS idx_coa_company_id ON chart_of_accounts(company_id);

-- ──────────────────────────────────────────────────────────────
-- TRANSACTIONS MODULE
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS transactions (
    id                    TEXT PRIMARY KEY,
    company_id            TEXT NOT NULL,
    import_batch_id       TEXT NOT NULL DEFAULT '',
    date                  TEXT NOT NULL DEFAULT '',
    account_code          TEXT NOT NULL DEFAULT '',
    account_name          TEXT NOT NULL DEFAULT '',
    description           TEXT NOT NULL DEFAULT '',
    reference             TEXT NOT NULL DEFAULT '',
    counterparty          TEXT NOT NULL DEFAULT '',
    debit                 DOUBLE PRECISION NOT NULL DEFAULT 0,
    credit                DOUBLE PRECISION NOT NULL DEFAULT 0,
    balance               DOUBLE PRECISION NOT NULL DEFAULT 0,
    currency              TEXT NOT NULL DEFAULT 'ETB',
    is_flagged            BOOLEAN NOT NULL DEFAULT FALSE,
    flag_reason           TEXT NOT NULL DEFAULT '',
    has_individual_name   BOOLEAN NOT NULL DEFAULT FALSE,
    individual_name_field TEXT NOT NULL DEFAULT '',
    review_status         TEXT NOT NULL DEFAULT 'pending',
    reviewer_notes        TEXT NOT NULL DEFAULT '',
    created_at            TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_transactions_company_id ON transactions(company_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_transactions_is_flagged ON transactions(is_flagged);

CREATE TABLE IF NOT EXISTS flagged_accounts (
    id           TEXT PRIMARY KEY,
    account_code TEXT NOT NULL DEFAULT '',
    account_name TEXT NOT NULL DEFAULT '',
    flag_reason  TEXT NOT NULL DEFAULT '',
    auto_flagged BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS transaction_import_history (
    id              TEXT PRIMARY KEY,
    filename        TEXT NOT NULL DEFAULT '',
    import_date     TEXT NOT NULL DEFAULT '',
    total_rows      BIGINT NOT NULL DEFAULT 0,
    imported_rows   BIGINT NOT NULL DEFAULT 0,
    flagged_rows    BIGINT NOT NULL DEFAULT 0,
    individual_name_rows BIGINT NOT NULL DEFAULT 0,
    errors          BIGINT NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT ''
);

-- ──────────────────────────────────────────────────────────────
-- INCOME / EXPENSE MODULE
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS income_records (
    id               TEXT PRIMARY KEY,
    company_id       TEXT NOT NULL,
    date             TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT '',
    category         TEXT NOT NULL DEFAULT '',
    client_name      TEXT NOT NULL DEFAULT '',
    client_tin       TEXT NOT NULL DEFAULT '',
    gross_amount     DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax_rate         DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax_amount       DOUBLE PRECISION NOT NULL DEFAULT 0,
    net_amount       DOUBLE PRECISION NOT NULL DEFAULT 0,
    payment_method   TEXT NOT NULL DEFAULT '',
    reference_number TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_income_records_company_id ON income_records(company_id);

CREATE TABLE IF NOT EXISTS expense_records (
    id               TEXT PRIMARY KEY,
    company_id       TEXT NOT NULL,
    date             TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT '',
    category         TEXT NOT NULL DEFAULT '',
    supplier_name    TEXT NOT NULL DEFAULT '',
    supplier_tin     TEXT NOT NULL DEFAULT '',
    gross_amount     DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax_rate         DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax_amount       DOUBLE PRECISION NOT NULL DEFAULT 0,
    net_amount       DOUBLE PRECISION NOT NULL DEFAULT 0,
    payment_method   TEXT NOT NULL DEFAULT '',
    receipt_number   TEXT NOT NULL DEFAULT '',
    is_deductible    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_expense_records_company_id ON expense_records(company_id);

-- ──────────────────────────────────────────────────────────────
-- INVENTORY MODULE
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS inventory_items (
    id               TEXT PRIMARY KEY,
    company_id       TEXT NOT NULL,
    sku              TEXT NOT NULL DEFAULT '',
    name             TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT '',
    category         TEXT NOT NULL DEFAULT '',
    unit             TEXT NOT NULL DEFAULT '',
    unit_price       DOUBLE PRECISION NOT NULL DEFAULT 0,
    cost_price       DOUBLE PRECISION NOT NULL DEFAULT 0,
    serial_number    TEXT NOT NULL DEFAULT '',
    batch_number     TEXT NOT NULL DEFAULT '',
    barcode          TEXT NOT NULL DEFAULT '',
    current_stock    DOUBLE PRECISION NOT NULL DEFAULT 0,
    min_stock_level  DOUBLE PRECISION NOT NULL DEFAULT 0,
    reorder_point    DOUBLE PRECISION NOT NULL DEFAULT 0,
    reorder_quantity DOUBLE PRECISION NOT NULL DEFAULT 0,
    location         TEXT NOT NULL DEFAULT '',
    is_rentable      TEXT NOT NULL DEFAULT 'false',
    status           TEXT NOT NULL DEFAULT 'active',
    valuation_method TEXT NOT NULL DEFAULT 'FIFO',
    created_at       TEXT NOT NULL DEFAULT '',
    updated_at       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_inventory_items_company_id ON inventory_items(company_id);

CREATE TABLE IF NOT EXISTS inventory_categories (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    parent_category TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS inventory_movements (
    id               TEXT PRIMARY KEY,
    item_id          TEXT NOT NULL,
    item_name        TEXT NOT NULL DEFAULT '',
    movement_type    TEXT NOT NULL DEFAULT '',
    quantity         DOUBLE PRECISION NOT NULL DEFAULT 0,
    unit_cost        DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_cost       DOUBLE PRECISION NOT NULL DEFAULT 0,
    from_location    TEXT NOT NULL DEFAULT '',
    to_location      TEXT NOT NULL DEFAULT '',
    reference_number TEXT NOT NULL DEFAULT '',
    reason           TEXT NOT NULL DEFAULT '',
    approved_by      TEXT NOT NULL DEFAULT '',
    approval_status  TEXT NOT NULL DEFAULT 'pending',
    date             TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_inventory_movements_item_id ON inventory_movements(item_id);

CREATE TABLE IF NOT EXISTS inventory_allocations (
    id                   TEXT PRIMARY KEY,
    item_id              TEXT NOT NULL,
    item_name            TEXT NOT NULL DEFAULT '',
    event_name           TEXT NOT NULL DEFAULT '',
    allocated_quantity   DOUBLE PRECISION NOT NULL DEFAULT 0,
    returned_quantity    DOUBLE PRECISION NOT NULL DEFAULT 0,
    allocation_date      TEXT NOT NULL DEFAULT '',
    expected_return_date TEXT NOT NULL DEFAULT '',
    actual_return_date   TEXT NOT NULL DEFAULT '',
    status               TEXT NOT NULL DEFAULT 'active',
    allocated_by         TEXT NOT NULL DEFAULT '',
    notes                TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS inventory_maintenance (
    id               TEXT PRIMARY KEY,
    item_id          TEXT NOT NULL,
    item_name        TEXT NOT NULL DEFAULT '',
    maintenance_type TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT '',
    scheduled_date   TEXT NOT NULL DEFAULT '',
    completed_date   TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'scheduled',
    assigned_to      TEXT NOT NULL DEFAULT '',
    cost             DOUBLE PRECISION NOT NULL DEFAULT 0,
    notes            TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS inventory_requisitions (
    id              TEXT PRIMARY KEY,
    item_id         TEXT NOT NULL,
    item_name       TEXT NOT NULL DEFAULT '',
    quantity_needed DOUBLE PRECISION NOT NULL DEFAULT 0,
    current_stock   DOUBLE PRECISION NOT NULL DEFAULT 0,
    reorder_point   DOUBLE PRECISION NOT NULL DEFAULT 0,
    estimated_cost  DOUBLE PRECISION NOT NULL DEFAULT 0,
    priority        TEXT NOT NULL DEFAULT 'medium',
    status          TEXT NOT NULL DEFAULT 'pending',
    requested_by    TEXT NOT NULL DEFAULT '',
    approved_by     TEXT NOT NULL DEFAULT '',
    supplier        TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',
    date            TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS inventory_import_history (
    id            TEXT PRIMARY KEY,
    filename      TEXT NOT NULL DEFAULT '',
    import_type   TEXT NOT NULL DEFAULT '',
    import_date   TEXT NOT NULL DEFAULT '',
    total_rows    BIGINT NOT NULL DEFAULT 0,
    imported_rows BIGINT NOT NULL DEFAULT 0,
    errors        BIGINT NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT ''
);

-- ──────────────────────────────────────────────────────────────
-- BID MODULE
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS bid_records (
    id                    TEXT PRIMARY KEY,
    company_id            TEXT NOT NULL,
    title                 TEXT NOT NULL DEFAULT '',
    reference_number      TEXT NOT NULL DEFAULT '',
    organization          TEXT NOT NULL DEFAULT '',
    description           TEXT NOT NULL DEFAULT '',
    category              TEXT NOT NULL DEFAULT '',
    status                TEXT NOT NULL DEFAULT 'open',
    deadline              TEXT NOT NULL DEFAULT '',
    submission_date       TEXT NOT NULL DEFAULT '',
    bid_amount            DOUBLE PRECISION NOT NULL DEFAULT 0,
    currency              TEXT NOT NULL DEFAULT 'ETB',
    case_handler_name     TEXT NOT NULL DEFAULT '',
    case_handler_email    TEXT NOT NULL DEFAULT '',
    reminder_days_before  BIGINT NOT NULL DEFAULT 3,
    reminder_sent         BOOLEAN NOT NULL DEFAULT FALSE,
    notes                 TEXT NOT NULL DEFAULT '',
    created_at            TEXT NOT NULL DEFAULT '',
    updated_at            TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_bid_records_company_id ON bid_records(company_id);

CREATE TABLE IF NOT EXISTS bid_documents_meta (
    id                TEXT PRIMARY KEY,
    bid_id            TEXT NOT NULL,
    filename          TEXT NOT NULL DEFAULT '',
    original_filename TEXT NOT NULL DEFAULT '',
    doc_type          TEXT NOT NULL DEFAULT '',
    description       TEXT NOT NULL DEFAULT '',
    uploaded_by       TEXT NOT NULL DEFAULT '',
    file_size         BIGINT NOT NULL DEFAULT 0,
    uploaded_at       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_bid_documents_bid_id ON bid_documents_meta(bid_id);

-- ──────────────────────────────────────────────────────────────
-- CPO MODULE
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cpo_records (
    id              TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL,
    import_batch_id TEXT NOT NULL DEFAULT '',
    name            TEXT NOT NULL DEFAULT '',
    date            TEXT NOT NULL DEFAULT '',
    amount          DOUBLE PRECISION NOT NULL DEFAULT 0,
    bid_name        TEXT NOT NULL DEFAULT '',
    is_returned     TEXT NOT NULL DEFAULT 'false',
    returned_date   TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_cpo_records_company_id ON cpo_records(company_id);

CREATE TABLE IF NOT EXISTS cpo_import_history (
    id            TEXT PRIMARY KEY,
    filename      TEXT NOT NULL DEFAULT '',
    import_date   TEXT NOT NULL DEFAULT '',
    total_rows    BIGINT NOT NULL DEFAULT 0,
    imported_rows BIGINT NOT NULL DEFAULT 0,
    errors        BIGINT NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT ''
);

-- ──────────────────────────────────────────────────────────────
-- SIEM / SECURITY MODULE
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS siem_events (
    event_id         TEXT PRIMARY KEY,
    timestamp        TEXT NOT NULL DEFAULT '',
    ip_address       TEXT NOT NULL DEFAULT '',
    username         TEXT NOT NULL DEFAULT '',
    module           TEXT NOT NULL DEFAULT '',
    endpoint         TEXT NOT NULL DEFAULT '',
    http_method      TEXT NOT NULL DEFAULT '',
    filename         TEXT NOT NULL DEFAULT '',
    file_size_bytes  INTEGER NOT NULL DEFAULT 0,
    records_imported INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT '',
    details          TEXT NOT NULL DEFAULT '',
    user_agent       TEXT NOT NULL DEFAULT '',
    referer          TEXT NOT NULL DEFAULT '',
    content_type     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_siem_events_timestamp  ON siem_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_siem_events_ip_address ON siem_events(ip_address);
CREATE INDEX IF NOT EXISTS idx_siem_events_module     ON siem_events(module);

CREATE TABLE IF NOT EXISTS siem_alerts (
    alert_id     TEXT PRIMARY KEY,
    timestamp    TEXT NOT NULL DEFAULT '',
    severity     TEXT NOT NULL DEFAULT 'medium',
    rule         TEXT NOT NULL DEFAULT '',
    message      TEXT NOT NULL DEFAULT '',
    event_id     TEXT NOT NULL DEFAULT '',
    ip_address   TEXT NOT NULL DEFAULT '',
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_siem_alerts_acknowledged ON siem_alerts(acknowledged);

-- ──────────────────────────────────────────────────────────────
-- EMPLOYEE MODULE
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS employees (
    employee_id          TEXT PRIMARY KEY,
    company_id           TEXT NOT NULL,
    name                 TEXT NOT NULL DEFAULT '',
    category             TEXT NOT NULL DEFAULT '',
    basic_salary         DOUBLE PRECISION NOT NULL DEFAULT 0,
    hire_date            DATE,
    department           TEXT NOT NULL DEFAULT '',
    position             TEXT NOT NULL DEFAULT '',
    bank_account         TEXT NOT NULL DEFAULT '',
    tin_number           TEXT NOT NULL DEFAULT '',
    pension_number       TEXT NOT NULL DEFAULT '',
    work_days_per_month  INTEGER NOT NULL DEFAULT 26,
    work_hours_per_day   INTEGER NOT NULL DEFAULT 8,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_date         TIMESTAMP,
    updated_date         TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_employees_company_id ON employees(company_id);

-- ──────────────────────────────────────────────────────────────
-- BACKUP LOG MODULE
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS backup_log (
    id                TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    archive_name      TEXT NOT NULL DEFAULT '',
    archive_path      TEXT NOT NULL DEFAULT '',
    file_count        INTEGER NOT NULL DEFAULT 0,
    original_size     BIGINT NOT NULL DEFAULT 0,
    compressed_size   BIGINT NOT NULL DEFAULT 0,
    compression_ratio DOUBLE PRECISION NOT NULL DEFAULT 0,
    timestamp         TEXT NOT NULL DEFAULT '',
    triggered_by      TEXT NOT NULL DEFAULT '',
    label             TEXT NOT NULL DEFAULT ''
);

-- ──────────────────────────────────────────────────────────────
-- VERSION MODULE (lightweight — stores version registry in DB)
-- ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS version_registry (
    version_id   TEXT PRIMARY KEY,
    version      TEXT NOT NULL UNIQUE,
    label        TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT '',
    is_active    BOOLEAN NOT NULL DEFAULT FALSE,
    changelog    TEXT NOT NULL DEFAULT ''
);
