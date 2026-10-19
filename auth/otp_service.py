"""One-time password (OTP) generation and verification.

SMS_PROVIDER=console: prints OTP to stdout (dev mode).
SMS_PROVIDER=twilio: sends via Twilio API.
"""
import os
import random
import time
import sqlite3
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path

from core.config import config


OTP_EXPIRY_MINUTES = int(os.getenv('OTP_EXPIRY_MINUTES', '10'))
OTP_MAX_ATTEMPTS = int(os.getenv('OTP_MAX_ATTEMPTS', '3'))
SMS_PROVIDER = os.getenv('SMS_PROVIDER', 'console')


@dataclass
class OtpResult:
    success: bool
    message: str
    remaining_attempts: int = 0


def generate_otp(length: int = 6) -> str:
    """Generate a numeric OTP code."""
    return ''.join(str(random.randint(0, 9)) for _ in range(length))


def store_otp(db_path: str, phone_hash: str, code: str, purpose: str = 'login') -> bool:
    """Store an OTP code in the database. Returns True on success."""
    expires_at = (datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)).strftime(
        '%Y-%m-%dT%H:%M:%SZ'
    )
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            # One live code per phone and purpose (the table is UNIQUE on both):
            # a new code replaces the old one. A plain INSERT crashed the Login
            # page the second time the same phone logged in, and on "Resend".
            conn.execute(
                "DELETE FROM phone_verification_code WHERE phone_hash = ? AND purpose = ?",
                (phone_hash, purpose),
            )
            conn.execute(
                """INSERT INTO phone_verification_code
                   (phone_hash, code, purpose, expires_at)
                   VALUES (?, ?, ?, ?)""",
                (phone_hash, code, purpose, expires_at)
            )
            conn.commit()
        return True
    except sqlite3.OperationalError:
        # Table might not exist yet
        return False


def verify_otp(db_path: str, phone_hash: str, code: str, purpose: str = 'login') -> OtpResult:
    """Verify an OTP code. Returns OtpResult with success/failure info."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            # The table's "code already used" column is verified_at (migration
            # 001); older databases may call it used_at. Use whichever exists,
            # otherwise every verification failed with "Database error".
            cols = {r[1] for r in conn.execute("PRAGMA table_info(phone_verification_code)")}
            used = "used_at" if "used_at" in cols else "verified_at"
            cursor = conn.execute(
                f"""SELECT code, attempts, expires_at
                   FROM phone_verification_code
                   WHERE phone_hash = ? AND purpose = ? AND {used} IS NULL
                   ORDER BY created_at DESC LIMIT 1""",
                (phone_hash, purpose)
            )
            row = cursor.fetchone()

            if not row:
                return OtpResult(success=False, message="No active OTP found. Request a new code.")

            # Check expiry
            expires_at = datetime.strptime(row['expires_at'], '%Y-%m-%dT%H:%M:%SZ')
            if datetime.utcnow() > expires_at:
                return OtpResult(success=False, message="OTP expired. Request a new code.")

            # Check attempts
            if row['attempts'] >= OTP_MAX_ATTEMPTS:
                return OtpResult(
                    success=False,
                    message="Too many attempts. Request a new code.",
                    remaining_attempts=0
                )

            remaining = OTP_MAX_ATTEMPTS - row['attempts'] - 1

            # Check code match
            if not _constant_time_compare(row['code'], code):
                # Increment attempts
                conn.execute(
                    f"""UPDATE phone_verification_code
                       SET attempts = attempts + 1
                       WHERE phone_hash = ? AND purpose = ? AND {used} IS NULL""",
                    (phone_hash, purpose)
                )
                conn.commit()
                return OtpResult(
                    success=False,
                    message=f"Incorrect OTP. {remaining} attempt(s) remaining.",
                    remaining_attempts=remaining
                )

            # Mark as used
            conn.execute(
                f"""UPDATE phone_verification_code
                   SET {used} = ?, attempts = attempts + 1
                   WHERE phone_hash = ? AND purpose = ? AND {used} IS NULL""",
                (datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), phone_hash, purpose)
            )
            conn.commit()

            return OtpResult(success=True, message="OTP verified.", remaining_attempts=remaining)

    except sqlite3.OperationalError:
        return OtpResult(success=False, message="Database error. Please try again.")


def send_otp(phone: str, code: str) -> bool:
    """Send OTP via the configured provider. Returns True if sent (or printed)."""
    if SMS_PROVIDER == 'console':
        print(f"\n{'='*50}")
        print(f"  📱 SMS OTP for {phone}: {code}")
        print(f"  Expires in {OTP_EXPIRY_MINUTES} minutes")
        print(f"{'='*50}\n")
        return True

    if SMS_PROVIDER == 'twilio':
        from integrations.sms import send_sms
        result = send_sms(
            phone,
            f"Your Duka verification code is: {code}. Expires in {OTP_EXPIRY_MINUTES} min.",
        )
        if not result.ok:
            print(f"Twilio send failed: {result.error}")
        return result.ok

    print(f"OTP for {phone}: {code}  (unknown provider: {SMS_PROVIDER})")
    return True


def _constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0
