-- =====================================================================
-- 005: Per-business owner settings and the owner's approval PIN
-- =====================================================================
-- Each business keeps its own rules (previously one global .env value):
-- payment caps, loan cap, safety buffer, staff payday and reply language.
-- Only the owner changes them, in Business Setup; caps and payees need the
-- owner PIN. The AI has no tool that touches these tables.
--
-- Verified payees live in the existing payee table (verified = 1).
-- Taught categories live in categorisation_rule (created_by = 'owner').
-- Idempotent: core/owner_settings.py also runs this on first use.

CREATE TABLE IF NOT EXISTS business_settings (
  business_id INTEGER PRIMARY KEY REFERENCES business(business_id),
  per_txn_cap_minor INTEGER NOT NULL CHECK (per_txn_cap_minor > 0),
  daily_cap_minor INTEGER NOT NULL CHECK (daily_cap_minor > 0),
  loan_cap_minor INTEGER NOT NULL CHECK (loan_cap_minor > 0),
  safety_buffer_minor INTEGER NOT NULL CHECK (safety_buffer_minor >= 0),
  payday_weekday INTEGER CHECK (payday_weekday IS NULL OR payday_weekday BETWEEN 0 AND 6),
  language TEXT NOT NULL DEFAULT 'en' CHECK (language IN ('en','sw')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_by_user_id INTEGER REFERENCES app_user(user_id),
  CHECK (daily_cap_minor >= per_txn_cap_minor)
);

-- The PIN itself is never stored: PBKDF2 hash + salt only.
CREATE TABLE IF NOT EXISTS owner_pin (
  business_id INTEGER PRIMARY KEY REFERENCES business(business_id),
  pin_hash TEXT NOT NULL,
  pin_salt TEXT NOT NULL,
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS ix_payee_biz_verified ON payee(business_id, verified, active);
