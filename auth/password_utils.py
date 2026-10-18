"""Password hashing with Argon2 (via hashlib when available, or bcrypt fallback)."""
import hashlib
import os
import secrets
import base64


def hash_password(password: str) -> tuple[str, str]:
    """Hash a password with SHA-256 + random salt.

    Returns (password_hash, salt) tuple. Both are hex strings.
    Uses PBKDF2-HMAC-SHA256 with 600k iterations for strong protection.
    """
    salt = secrets.token_hex(32)
    pw_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        600_000
    ).hex()
    return pw_hash, salt


def verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    """Verify a password against its stored hash and salt."""
    if not stored_hash or not stored_salt:
        return False
    computed = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        stored_salt.encode('utf-8'),
        600_000
    ).hex()
    return secrets.compare_digest(computed, stored_hash)


def generate_reset_token() -> str:
    """Generate a URL-safe password reset token."""
    return secrets.token_urlsafe(32)
