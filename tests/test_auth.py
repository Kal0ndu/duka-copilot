"""Unit tests for auth module: phone, password, OTP, session, users."""
import sys
import os
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from auth.phone_utils import (
    normalise_phone, hash_phone, hash_email,
    mask_phone, is_valid_kenyan_phone,
)
from auth.password_utils import (
    hash_password, verify_password, generate_reset_token,
)
from auth.otp_service import generate_otp, store_otp, verify_otp, OtpResult
from auth.session_manager import (
    create_session, decode_session, Session,
    persist_session, revoke_session,
)
from db.users import (
    create_user, get_user_by_phone, get_user_by_id,
    get_user_password, update_password,
    mark_phone_verified, update_last_login,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path():
    """Create a temporary SQLite database with required tables."""
    import sqlite3
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS app_user (
            user_id INTEGER PRIMARY KEY,
            display_token TEXT NOT NULL,
            locale TEXT NOT NULL DEFAULT 'en',
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            phone_hash TEXT,
            phone_verified INTEGER NOT NULL DEFAULT 0 CHECK (phone_verified IN (0,1)),
            email_hash TEXT,
            email_verified INTEGER NOT NULL DEFAULT 0 CHECK (email_verified IN (0,1)),
            display_name TEXT,
            password_hash TEXT,
            password_salt TEXT,
            timezone TEXT NOT NULL DEFAULT 'Africa/Nairobi',
            last_login_at TEXT,
            last_login_ip TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS phone_verification_code (
            id INTEGER PRIMARY KEY,
            phone_hash TEXT NOT NULL,
            code TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT 'login',
            attempts INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ix_app_user_phone ON app_user(phone_hash);
        CREATE TABLE IF NOT EXISTS authentication_session (
            session_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            phone_hash TEXT,
            business_id INTEGER NOT NULL DEFAULT 0,
            jwt_token_hash TEXT NOT NULL,
            ip_address TEXT NOT NULL DEFAULT '127.0.0.1',
            user_agent TEXT NOT NULL DEFAULT '',
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_activity_at TEXT NOT NULL,
            revoked_at TEXT,
            revoke_reason TEXT,
            FOREIGN KEY (user_id) REFERENCES app_user(user_id)
        );
    """)
    conn.commit()
    conn.close()

    yield path
    os.unlink(path)


@pytest.fixture
def test_user(db_path):
    """Create a test user and return the UserRecord."""
    from auth.phone_utils import hash_phone
    ph = hash_phone("+254700000001")
    pw_hash, pw_salt = hash_password("securepass1")
    uid = create_user(db_path, phone_hash=ph, display_name="Test User",
                      password_hash=pw_hash, password_salt=pw_salt)
    user = get_user_by_id(db_path, uid)
    return user


# ---------------------------------------------------------------------------
# Phone utils
# ---------------------------------------------------------------------------

class TestPhoneUtils:
    def test_normalise_07_prefix(self):
        assert normalise_phone("0712 345 678") == "+254712345678"

    def test_normalise_254_prefix(self):
        assert normalise_phone("254712345678") == "+254712345678"

    def test_normalise_plus254_prefix(self):
        assert normalise_phone("+254712345678") == "+254712345678"

    def test_normalise_7_prefix(self):
        assert normalise_phone("712345678") == "+254712345678"

    def test_normalise_invalid(self):
        with pytest.raises(ValueError):
            normalise_phone("12345")

    def test_is_valid(self):
        assert is_valid_kenyan_phone("0712 345 678")
        assert is_valid_kenyan_phone("+254712345678")
        assert not is_valid_kenyan_phone("not-a-number")
        assert not is_valid_kenyan_phone("+1234567890")

    def test_hash_deterministic(self):
        h1 = hash_phone("+254700000001")
        h2 = hash_phone("+254700000001")
        assert h1 == h2
        assert len(h1) == 64

    def test_hash_email(self):
        h = hash_email("Test@Example.Com")
        assert len(h) == 64
        # Should be lowercased
        assert h == hash_email("test@example.com")

    def test_mask_phone(self):
        masked = mask_phone("+254712345678")
        assert "712" in masked
        assert "678" in masked
        assert len(masked) > 10


# ---------------------------------------------------------------------------
# Password utils
# ---------------------------------------------------------------------------

class TestPasswordUtils:
    def test_hash_and_verify(self):
        pw_hash, salt = hash_password("mysecretpass")
        assert len(pw_hash) == 64
        assert len(salt) == 64
        assert verify_password("mysecretpass", pw_hash, salt)
        assert not verify_password("wrongpass", pw_hash, salt)

    def test_empty_salt_rejected(self):
        assert not verify_password("anything", "", "")

    def test_different_salts(self):
        h1, s1 = hash_password("same")
        h2, s2 = hash_password("same")
        assert s1 != s2  # salts should be unique
        assert h1 != h2  # hashes differ with different salts
        assert verify_password("same", h1, s1)
        assert verify_password("same", h2, s2)

    def test_reset_token_length(self):
        token = generate_reset_token()
        assert len(token) >= 32


# ---------------------------------------------------------------------------
# OTP service
# ---------------------------------------------------------------------------

class TestOtpService:
    def test_generate_otp_length(self):
        otp = generate_otp()
        assert len(otp) == 6
        assert otp.isdigit()

    def test_generate_otp_custom_length(self):
        otp = generate_otp(4)
        assert len(otp) == 4

    def test_store_and_verify_otp(self, db_path):
        ph = hash_phone("+254700000010")
        otp = generate_otp()
        assert store_otp(db_path, ph, otp, "login")

        result = verify_otp(db_path, ph, otp, "login")
        assert result.success
        assert result.message == "OTP verified."

    def test_wrong_otp(self, db_path):
        ph = hash_phone("+254700000011")
        otp = generate_otp()
        store_otp(db_path, ph, otp, "login")

        result = verify_otp(db_path, ph, "000000", "login")
        assert not result.success
        assert "Incorrect" in result.message

    def test_no_otp_found(self, db_path):
        ph = hash_phone("+254700000012")
        result = verify_otp(db_path, ph, "123456", "login")
        assert not result.success
        assert "No active OTP" in result.message

    def test_otp_purpose_isolation(self, db_path):
        ph = hash_phone("+254700000013")
        otp = generate_otp()
        store_otp(db_path, ph, otp, "signup")
        result = verify_otp(db_path, ph, otp, "login")
        assert not result.success


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------

class TestSessionManager:
    def test_create_and_decode(self):
        token = create_session(1, 0, "Test", "owner", "abc123")
        assert token.count('.') == 2

        session = decode_session(token)
        assert session is not None
        assert session.user_id == 1
        assert session.display_name == "Test"
        assert session.role == "owner"
        assert session.phone_hash == "abc123"
        assert not session.is_expired()
        assert session.is_authenticated

    def test_invalid_token(self):
        assert decode_session("garbage") is None
        assert decode_session("a.b.c") is None
        assert decode_session("") is None

    def test_tampered_token(self):
        token = create_session(1, 0, "Test", "owner")
        parts = token.split('.')
        tampered = parts[0] + ".tamperedpayload." + parts[2]
        assert decode_session(tampered) is None

    def test_persist_session(self, db_path):
        from auth.phone_utils import hash_phone
        from auth.password_utils import hash_password
        from db.users import create_user

        ph = hash_phone("+254700000030")
        pw_hash, pw_salt = hash_password("testpass")
        uid = create_user(db_path, phone_hash=ph, display_name="SessionTest",
                          password_hash=pw_hash, password_salt=pw_salt)

        token = create_session(uid, 0, "SessionTest", "owner")
        session = decode_session(token)
        ok = persist_session(db_path, session, token)
        assert ok is True


# ---------------------------------------------------------------------------
# DB Users
# ---------------------------------------------------------------------------

class TestDbUsers:
    def test_create_and_lookup(self, db_path):
        ph = hash_phone("+254700000020")
        pw_hash, pw_salt = hash_password("testpass")
        uid = create_user(db_path, phone_hash=ph, display_name="Alice",
                          password_hash=pw_hash, password_salt=pw_salt)
        assert uid is not None
        assert uid > 0

        user = get_user_by_phone(db_path, ph)
        assert user is not None
        assert user.display_name == "Alice"
        assert user.phone_verified is False
        assert user.status == "active"

    def test_duplicate_phone(self, db_path):
        ph = hash_phone("+254700000021")
        pw_hash, pw_salt = hash_password("testpass")
        uid1 = create_user(db_path, phone_hash=ph, display_name="Bob",
                           password_hash=pw_hash, password_salt=pw_salt)
        assert uid1 is not None
        uid2 = create_user(db_path, phone_hash=ph, display_name="Bob2",
                           password_hash=pw_hash, password_salt=pw_salt)
        assert uid2 is None  # Should reject duplicate

    def test_get_by_id(self, db_path):
        ph = hash_phone("+254700000022")
        pw_hash, pw_salt = hash_password("testpass")
        uid = create_user(db_path, phone_hash=ph, display_name="Carol",
                          password_hash=pw_hash, password_salt=pw_salt)
        user = get_user_by_id(db_path, uid)
        assert user.display_name == "Carol"

    def test_get_nonexistent(self, db_path):
        assert get_user_by_phone(db_path, "nonexistent_hash") is None
        assert get_user_by_id(db_path, 99999) is None

    def test_get_password(self, db_path):
        ph = hash_phone("+254700000023")
        pw_hash, pw_salt = hash_password("mypassword")
        uid = create_user(db_path, phone_hash=ph, display_name="Dave",
                          password_hash=pw_hash, password_salt=pw_salt)
        stored_hash, stored_salt = get_user_password(db_path, uid)
        assert verify_password("mypassword", stored_hash, stored_salt)
        assert not verify_password("wrong", stored_hash, stored_salt)

    def test_update_password(self, db_path):
        ph = hash_phone("+254700000024")
        pw_hash, pw_salt = hash_password("oldpass")
        uid = create_user(db_path, phone_hash=ph, display_name="Eve",
                          password_hash=pw_hash, password_salt=pw_salt)

        new_hash, new_salt = hash_password("newpass")
        ok = update_password(db_path, uid, new_hash, new_salt)
        assert ok

        stored_hash, stored_salt = get_user_password(db_path, uid)
        assert verify_password("newpass", stored_hash, stored_salt)
        assert not verify_password("oldpass", stored_hash, stored_salt)

    def test_mark_phone_verified(self, db_path):
        ph = hash_phone("+254700000025")
        pw_hash, pw_salt = hash_password("testpass")
        uid = create_user(db_path, phone_hash=ph, display_name="Frank",
                          password_hash=pw_hash, password_salt=pw_salt)

        user_before = get_user_by_id(db_path, uid)
        assert user_before.phone_verified is False

        ok = mark_phone_verified(db_path, uid)
        assert ok

        user_after = get_user_by_id(db_path, uid)
        assert user_after.phone_verified is True

    def test_update_last_login(self, db_path):
        ph = hash_phone("+254700000026")
        pw_hash, pw_salt = hash_password("testpass")
        uid = create_user(db_path, phone_hash=ph, display_name="Grace",
                          password_hash=pw_hash, password_salt=pw_salt)

        ok = update_last_login(db_path, uid, ip_address="192.168.1.1")
        assert ok

        user = get_user_by_id(db_path, uid)
        assert user.last_login_at is not None
