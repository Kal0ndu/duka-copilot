-- =====================================================================
-- Migration 001: Multi-User Authentication & KYC Schema
-- Date: 2026-10-18
-- Description: Add authentication, KYC, session management, and audit tables
-- =====================================================================
-- This migration adds 5 new tables and modifies the business table
-- to support multi-user authentication with business isolation.
-- =====================================================================

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

-- =====================================================================
-- TABLE 1: app_user (Core user authentication)
-- =====================================================================
-- app_user already exists from db/schema.sql's base definition (user_id,
-- phone_hash, phone_verified, display_name, display_token, locale, status,
-- created_at) — add the auth columns this migration needs instead of
-- CREATE TABLE IF NOT EXISTS, which would silently no-op against the
-- existing table and skip every column below.
ALTER TABLE app_user ADD COLUMN email_hash TEXT;
ALTER TABLE app_user ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0 CHECK (email_verified IN (0,1));
ALTER TABLE app_user ADD COLUMN password_hash TEXT;
ALTER TABLE app_user ADD COLUMN password_salt TEXT;
ALTER TABLE app_user ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Africa/Nairobi';
ALTER TABLE app_user ADD COLUMN last_login_at TEXT;
ALTER TABLE app_user ADD COLUMN last_login_ip TEXT;
ALTER TABLE app_user ADD COLUMN updated_at TEXT;

CREATE INDEX IF NOT EXISTS ix_app_user_phone ON app_user(phone_hash);
CREATE UNIQUE INDEX IF NOT EXISTS ux_app_user_email ON app_user(email_hash);
CREATE INDEX IF NOT EXISTS ix_app_user_status ON app_user(status) WHERE status != 'active';

-- =====================================================================
-- TABLE 2: kyc_profile (Know Your Customer verification)
-- =====================================================================
CREATE TABLE IF NOT EXISTS kyc_profile (
  kyc_id INTEGER PRIMARY KEY AUTOINCREMENT,
  
  -- Link to user
  user_id INTEGER NOT NULL UNIQUE REFERENCES app_user(user_id) ON DELETE CASCADE,
  phone_hash TEXT REFERENCES app_user(phone_hash),
  
  -- KYC Status
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','verified','flagged')),
  
  -- Identity Information
  national_id_number_hash TEXT,
  national_id_verified_at TEXT,
  id_document_url TEXT,  -- Encrypted S3 URI; format: "s3://bucket/encrypted-{id}"
  
  -- Phone Verification
  phone_verification_code TEXT,
  phone_verified_at TEXT,
  
  -- Address
  physical_address TEXT,
  postal_code TEXT,
  
  -- Business Context
  business_registration_number TEXT,
  tax_pin_token TEXT,  -- Encrypted via token_vault; never stored in plain
  
  -- Sanctions Check
  sanctions_checked_at TEXT,
  sanctions_result TEXT CHECK (sanctions_result IN ('clear','flagged','manual_review')),
  sanctions_checker TEXT,  -- Which external service (e.g., 'OpenSanctions', 'internal_blocklist')
  
  -- Audit
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  verified_at TEXT,
  flagged_reason TEXT,
  reviewer_notes TEXT
);

CREATE INDEX IF NOT EXISTS ix_kyc_status ON kyc_profile(status);
CREATE INDEX IF NOT EXISTS ix_kyc_sanctions ON kyc_profile(sanctions_result) WHERE sanctions_result IS NOT NULL;

-- =====================================================================
-- TABLE 3: authentication_session (Active user sessions)
-- =====================================================================
CREATE TABLE IF NOT EXISTS authentication_session (
  session_id INTEGER PRIMARY KEY AUTOINCREMENT,
  
  -- User & Business Context
  user_id INTEGER NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
  phone_hash TEXT REFERENCES app_user(phone_hash),
  business_id INTEGER NOT NULL REFERENCES business(business_id) ON DELETE CASCADE,
  
  -- JWT Token Tracking (store hash, never raw token)
  jwt_token_hash TEXT NOT NULL UNIQUE,
  
  -- Session Metadata
  ip_address TEXT NOT NULL,
  user_agent TEXT,
  
  -- Timing
  issued_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  expires_at TEXT NOT NULL,
  last_activity_at TEXT,
  
  -- Revocation
  revoked_at TEXT,
  revoke_reason TEXT CHECK (revoke_reason IN ('logout','timeout','admin_revoke','password_change','device_mismatch')),
  
  UNIQUE (user_id, business_id, jwt_token_hash)
);

CREATE INDEX IF NOT EXISTS ix_session_user_business ON authentication_session(user_id, business_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_session_expires ON authentication_session(expires_at) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_session_token ON authentication_session(jwt_token_hash) WHERE revoked_at IS NULL;

-- =====================================================================
-- TABLE 4: phone_verification_code (OTP management)
-- =====================================================================
CREATE TABLE IF NOT EXISTS phone_verification_code (
  code_id INTEGER PRIMARY KEY AUTOINCREMENT,
  
  -- Phone reference
  phone_hash TEXT NOT NULL,
  
  -- Code details
  code TEXT NOT NULL,  -- 6-digit OTP
  purpose TEXT NOT NULL CHECK (purpose IN ('signup','login','password_reset','kyc_verify')),
  
  -- Attempt tracking
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  
  -- Timing
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  expires_at TEXT NOT NULL,
  verified_at TEXT,
  
  UNIQUE (phone_hash, purpose)
);

CREATE INDEX IF NOT EXISTS ix_otp_expires ON phone_verification_code(expires_at) WHERE verified_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_otp_phone_purpose ON phone_verification_code(phone_hash, purpose);

-- =====================================================================
-- TABLE 5: audit_login (Login activity audit trail)
-- =====================================================================
CREATE TABLE IF NOT EXISTS audit_login (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  
  -- Actor (user_id may be NULL for failed login attempts)
  user_id INTEGER REFERENCES app_user(user_id) ON DELETE SET NULL,
  phone_hash TEXT,  -- For failed logins or phone-based events
  
  -- Context
  business_id INTEGER REFERENCES business(business_id) ON DELETE SET NULL,
  
  -- Event
  event_type TEXT NOT NULL CHECK (event_type IN (
    'login_success','login_failed','logout',
    'password_reset','password_change',
    'kyc_submitted','kyc_verified','kyc_flagged',
    'account_created','account_deleted',
    'session_revoked','otp_sent','otp_failed'
  )),
  details TEXT,
  
  -- Request metadata
  ip_address TEXT,
  user_agent TEXT,
  
  -- Timestamp
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS ix_audit_user ON audit_login(user_id, created_at) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_audit_event ON audit_login(event_type, created_at);
CREATE INDEX IF NOT EXISTS ix_audit_phone ON audit_login(phone_hash, created_at) WHERE phone_hash IS NOT NULL;

-- =====================================================================
-- TABLE 6: business_member (Multi-role business access)
-- =====================================================================
-- business_member already exists from db/schema.sql (business_id, user_id,
-- phone_hash NOT NULL, role; composite PRIMARY KEY (business_id, user_id)).
-- CREATE TABLE IF NOT EXISTS would silently no-op here too, so add the
-- missing columns db/sessions.py depends on (member_id, is_active, added_at,
-- updated_at) instead. SQLite can't ALTER in a new INTEGER PRIMARY KEY onto
-- an existing table, so member_id is backed by the table's implicit rowid
-- (business_member isn't WITHOUT ROWID) via a trigger, giving the same
-- auto-incrementing-identifier behaviour db/sessions.py expects from
-- cursor.lastrowid.
ALTER TABLE business_member ADD COLUMN member_id INTEGER;
ALTER TABLE business_member ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1));
ALTER TABLE business_member ADD COLUMN added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'));
ALTER TABLE business_member ADD COLUMN updated_at TEXT;

UPDATE business_member SET member_id = rowid WHERE member_id IS NULL;

CREATE TRIGGER IF NOT EXISTS trg_business_member_id
AFTER INSERT ON business_member
WHEN NEW.member_id IS NULL
BEGIN
  UPDATE business_member SET member_id = NEW.rowid WHERE rowid = NEW.rowid;
END;

CREATE UNIQUE INDEX IF NOT EXISTS ux_business_member_id ON business_member(member_id);
CREATE INDEX IF NOT EXISTS ix_business_member_user ON business_member(user_id, is_active);
CREATE INDEX IF NOT EXISTS ix_business_member_role ON business_member(business_id, role);

-- =====================================================================
-- TABLE 7: business_invite (Multi-role team invitations)
-- =====================================================================
CREATE TABLE IF NOT EXISTS business_invite (
  invite_id INTEGER PRIMARY KEY AUTOINCREMENT,
  business_id INTEGER NOT NULL REFERENCES business(business_id) ON DELETE CASCADE,
  invited_by_user_id INTEGER NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
  
  -- Invite target
  email_hash TEXT,
  phone_hash TEXT,
  
  -- Invite details
  role TEXT NOT NULL CHECK (role IN ('manager','accountant','viewer')),
  invite_code TEXT NOT NULL UNIQUE,
  
  -- Status
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','rejected','expired')),
  accepted_by_user_id INTEGER REFERENCES app_user(user_id) ON DELETE SET NULL,
  
  -- Timing
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  expires_at TEXT NOT NULL,
  accepted_at TEXT
  
);
CREATE INDEX IF NOT EXISTS ix_invite_code ON business_invite(invite_code);
CREATE INDEX IF NOT EXISTS ix_invite_business_status ON business_invite(business_id, status);

-- =====================================================================
-- MODIFY: business table (Add ownership & KYC fields)
-- =====================================================================
-- owner_user_id already exists in db/schema.sql's base business table.
ALTER TABLE business ADD COLUMN kyc_required INTEGER NOT NULL DEFAULT 1 CHECK (kyc_required IN (0,1));
ALTER TABLE business ADD COLUMN kyc_verified_by_user_id INTEGER REFERENCES app_user(user_id);
ALTER TABLE business ADD COLUMN kyc_verified_at TEXT;

CREATE INDEX IF NOT EXISTS ix_business_owner ON business(owner_user_id);

-- =====================================================================
-- VIEWS: Useful queries for auth/KYC flows
-- =====================================================================

-- View: Active sessions for a user
CREATE VIEW IF NOT EXISTS v_active_sessions AS
SELECT 
  session_id,
  user_id,
  business_id,
  issued_at,
  expires_at,
  last_activity_at
FROM authentication_session
WHERE revoked_at IS NULL
  AND datetime(expires_at) > datetime('now');

-- View: User with KYC status
CREATE VIEW IF NOT EXISTS v_user_kyc_status AS
SELECT 
  u.user_id,
  u.phone_hash,
  u.display_name,
  u.phone_verified,
  COALESCE(k.status, 'no_profile') AS kyc_status,
  COALESCE(k.verified_at, NULL) AS kyc_verified_at,
  COALESCE(k.sanctions_result, NULL) AS sanctions_result,
  COALESCE(k.flagged_reason, NULL) AS kyc_flag_reason
FROM app_user u
LEFT JOIN kyc_profile k ON u.user_id = k.user_id;

-- View: Business with members and roles
CREATE VIEW IF NOT EXISTS v_business_with_members AS
SELECT 
  b.business_id,
  b.name_token,
  bm.user_id,
  bm.phone_hash,
  u.display_name,
  bm.role,
  bm.is_active
FROM business b
LEFT JOIN business_member bm ON b.business_id = bm.business_id
LEFT JOIN app_user u ON bm.user_id = u.user_id;

-- =====================================================================
-- CLEANUP JOBS (DDL for future implementation)
-- =====================================================================
-- Note: These should be implemented as background jobs in Python
-- - Delete expired OTP codes daily (older than 24h)
-- - Revoke expired sessions daily (after expires_at)
-- - Expire pending invites after 7 days
-- - Archive audit_login older than 7 years (compliance retention)

COMMIT;

-- =====================================================================
-- Verification: Count new tables
-- =====================================================================
-- After migration, run: SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%auth%' OR name LIKE '%kyc%';
-- Expected: 7 tables (app_user, kyc_profile, authentication_session, phone_verification_code, audit_login, business_member, business_invite)
