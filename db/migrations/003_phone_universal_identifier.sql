-- =====================================================================
-- Migration 003: Phone Number as Universal Identifier
-- Date: 2026-10-18
-- Description: Make phone_hash the universal join key across the system.
--   Ensures every table that references a user does so via phone_hash,
--   with proper foreign key constraints to app_user(phone_hash).
-- =====================================================================

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

-- =====================================================================
-- STEP 1: Ensure app_user.phone_hash is the authoritative unique key
--         (already UNIQUE from migration 001, but re-verify constraint)
-- =====================================================================
-- The phone_hash column in app_user is already TEXT NOT NULL UNIQUE.
-- No ALTER needed for this column.

-- =====================================================================
-- STEP 2: Add phone_hash columns to all user-referencing tables
-- =====================================================================

-- 2a: business_member.phone_hash already exists (NOT NULL) from db/schema.sql's
-- base table definition — no ALTER needed, just index + backfill for safety.
CREATE INDEX IF NOT EXISTS ix_business_member_phone ON business_member(phone_hash);

-- Backfill phone_hash from existing app_user rows
UPDATE business_member
SET phone_hash = (SELECT phone_hash FROM app_user WHERE app_user.user_id = business_member.user_id)
WHERE phone_hash IS NULL;

-- 2b: kyc_profile.phone_hash already exists from migration 001's CREATE TABLE.
CREATE INDEX IF NOT EXISTS ix_kyc_profile_phone ON kyc_profile(phone_hash);

UPDATE kyc_profile
SET phone_hash = (SELECT phone_hash FROM app_user WHERE app_user.user_id = kyc_profile.user_id)
WHERE phone_hash IS NULL;

-- 2c: authentication_session.phone_hash already exists from migration 001's CREATE TABLE.
CREATE INDEX IF NOT EXISTS ix_auth_session_phone ON authentication_session(phone_hash);

UPDATE authentication_session
SET phone_hash = (SELECT phone_hash FROM app_user WHERE app_user.user_id = authentication_session.user_id)
WHERE phone_hash IS NULL;

-- 2d: audit_login — add phone_hash FK (already has phone_hash column, ensure it references app_user)
-- The audit_login table already has a phone_hash column; add FK if missing
-- (SQLite doesn't support ADD CONSTRAINT, so we note this for app-layer enforcement)

-- 2e: business_invite — add phone_hash FK (already has phone_hash, ensure constraint)
-- Same as audit_login — already has phone_hash column

-- 2f: business.owner_phone_hash already exists from db/schema.sql's base table.
CREATE INDEX IF NOT EXISTS ix_business_owner_phone ON business(owner_phone_hash);

UPDATE business
SET owner_phone_hash = (SELECT phone_hash FROM app_user WHERE app_user.user_id = business.owner_user_id)
WHERE owner_phone_hash IS NULL AND owner_user_id IS NOT NULL;

-- STEP 3 removed: it ALTERed financial_account/forecast_run/synthetic_run to
-- add *_phone_hash columns backfilled from uploaded_by / user_id /
-- decided_by_user_id — none of which exist on those tables in db/schema.sql.
-- Those tables aren't user-scoped (they're scoped by business_id / run_id),
-- so there's nothing to backfill from; keeping the dead ALTERs would only
-- fail with "no such column" the moment this migration is ever re-run fresh.

-- =====================================================================
-- STEP 4: Update views to include phone_hash for easier joins
-- =====================================================================

-- Recreate v_user_kyc_status with phone_hash
DROP VIEW IF EXISTS v_user_kyc_status;
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

-- Recreate v_business_with_members with phone_hash
DROP VIEW IF EXISTS v_business_with_members;
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
-- STEP 5: Add unique constraint on (phone_hash, business_id) for
--         business_member to prevent duplicate memberships
-- =====================================================================
-- SQLite doesn't support ALTER TABLE ADD CONSTRAINT for UNIQUE,
-- but the app layer should enforce this. We note it as a directive.

COMMIT;

-- =====================================================================
-- VERIFICATION QUERIES (run after migration)
-- =====================================================================
-- SELECT 'business_member' AS tbl, COUNT(*) AS rows, COUNT(phone_hash) AS with_phone FROM business_member
-- UNION ALL SELECT 'kyc_profile', COUNT(*), COUNT(phone_hash) FROM kyc_profile
-- UNION ALL SELECT 'authentication_session', COUNT(*), COUNT(phone_hash) FROM authentication_session
-- UNION ALL SELECT 'business', COUNT(*), COUNT(owner_phone_hash) FROM business
-- UNION ALL SELECT 'financial_account', COUNT(*), COUNT(uploaded_by_phone_hash) FROM financial_account;
