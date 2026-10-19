-- =====================================================================
-- 006: Recurring-expense schedules and account roles (admin / user)
-- =====================================================================
-- Recurring expenses record when they were last paid and repeat every
-- N units of their cadence (see core/recurrence.py). next_due is derived
-- from last_paid_date; countdowns are computed at read time.
--
-- Accounts are 'user' unless promoted to the single 'admin' with
-- scripts/set_admin.py. The partial unique index allows at most one admin,
-- and the trigger refuses any account created as admin, so sign-up can
-- never create one. Only the admin may read audit logs and security events.
--
-- revoked_session holds the JWT ids of logged-out sessions so a copied
-- token stops working after logout.
-- core/rbac.py applies this file on first use if migrate.py has not.

ALTER TABLE recurring_expense ADD COLUMN last_paid_date TEXT;
ALTER TABLE recurring_expense ADD COLUMN interval_count INTEGER NOT NULL DEFAULT 1
  CHECK (interval_count BETWEEN 1 AND 365);

ALTER TABLE app_user ADD COLUMN account_role TEXT NOT NULL DEFAULT 'user'
  CHECK (account_role IN ('admin','user'));

CREATE UNIQUE INDEX IF NOT EXISTS ux_app_user_single_admin
  ON app_user(account_role) WHERE account_role = 'admin';

CREATE TRIGGER IF NOT EXISTS trg_app_user_no_admin_insert
BEFORE INSERT ON app_user
WHEN NEW.account_role = 'admin'
BEGIN
  SELECT RAISE(ABORT, 'admin accounts cannot be created directly');
END;

CREATE TABLE IF NOT EXISTS revoked_session (
  jti TEXT PRIMARY KEY,
  user_id INTEGER REFERENCES app_user(user_id),
  reason TEXT NOT NULL DEFAULT 'logout',
  revoked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
