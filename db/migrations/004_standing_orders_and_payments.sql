-- =====================================================================
-- Migration 004: Standing orders, payment notifications, M-Pesa STK
-- Date: 2026-10-18
-- Description: Owner-defined standing orders (like M-Pesa Ratiba) that
--   generate scheduled payments. The AI ranks them and the system sends
--   reminders, but nothing is paid until the owner taps Authorize and
--   then enters their M-Pesa PIN on the STK prompt.
-- =====================================================================

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS standing_order (
  standing_order_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  created_by_user_id INTEGER REFERENCES app_user(user_id),
  label TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('rent','loan_repayment','utility','wages','tax','school_fees','insurance','supplier_standing','savings','other')),
  destination_type TEXT NOT NULL CHECK (destination_type IN ('paybill','till','phone')),
  destination_number TEXT NOT NULL,
  account_reference TEXT,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0 AND amount_minor % 100 = 0),
  cadence TEXT NOT NULL CHECK (cadence IN ('weekly','biweekly','monthly','quarterly','one_off')),
  start_date TEXT NOT NULL,
  next_due TEXT,
  end_date TEXT,
  essential INTEGER NOT NULL DEFAULT 1 CHECK (essential IN (0,1)),
  late_penalty_minor INTEGER NOT NULL DEFAULT 0 CHECK (late_penalty_minor >= 0),
  remind_days_before INTEGER NOT NULL DEFAULT 2 CHECK (remind_days_before BETWEEN 0 AND 14),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','ended')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_so_due ON standing_order(business_id, next_due) WHERE status = 'active';

-- One row per due date of a standing order. Status flow:
--   pending -> notified -> authorized -> stk_sent -> paid | failed
--   (pending|notified) -> skipped ; failed -> authorized (retry)
CREATE TABLE IF NOT EXISTS scheduled_payment (
  payment_id INTEGER PRIMARY KEY,
  standing_order_id INTEGER NOT NULL REFERENCES standing_order(standing_order_id),
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  due_date TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  priority_score INTEGER NOT NULL DEFAULT 0 CHECK (priority_score BETWEEN 0 AND 100),
  priority_band TEXT NOT NULL DEFAULT 'low' CHECK (priority_band IN ('critical','high','medium','low')),
  priority_reasons_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','notified','authorized','stk_sent','paid','failed','skipped')),
  notified_at TEXT,
  authorized_by_user_id INTEGER REFERENCES app_user(user_id),
  authorized_at TEXT,
  paid_at TEXT,
  mpesa_receipt TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  UNIQUE (standing_order_id, due_date)
);
CREATE INDEX IF NOT EXISTS ix_sp_biz_status ON scheduled_payment(business_id, status);

CREATE TABLE IF NOT EXISTS mpesa_stk_request (
  stk_id INTEGER PRIMARY KEY,
  payment_id INTEGER NOT NULL REFERENCES scheduled_payment(payment_id),
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  environment TEXT NOT NULL CHECK (environment IN ('sandbox','production','simulated')),
  merchant_request_id TEXT,
  checkout_request_id TEXT UNIQUE,
  phone_hash TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  status TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('sent','success','failed','cancelled','timeout')),
  result_code TEXT,
  result_desc TEXT,
  mpesa_receipt TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_stk_payment ON mpesa_stk_request(payment_id);

CREATE TABLE IF NOT EXISTS notification (
  notification_id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  user_id INTEGER REFERENCES app_user(user_id),
  payment_id INTEGER REFERENCES scheduled_payment(payment_id),
  channel TEXT NOT NULL CHECK (channel IN ('in_app','sms')),
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sent','failed','read')),
  provider_ref TEXT,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  read_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_notif_unread ON notification(business_id, status) WHERE channel = 'in_app';

-- The phone that receives SMS reminders and STK prompts. The number itself
-- lives in token_vault; it must hash to the owner's login phone_hash so a
-- prompt can never be pushed to someone else's phone.
CREATE TABLE IF NOT EXISTS notification_contact (
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  user_id INTEGER NOT NULL REFERENCES app_user(user_id),
  phone_token TEXT NOT NULL,
  phone_hash TEXT NOT NULL,
  sms_enabled INTEGER NOT NULL DEFAULT 1 CHECK (sms_enabled IN (0,1)),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  PRIMARY KEY (business_id, user_id)
);

COMMIT;
