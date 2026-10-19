"""JWT session management — create, validate, revoke sessions."""
import os
import hmac
import hashlib
import json
import time
import sqlite3
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

from core.config import config


JWT_SECRET = os.getenv('JWT_SECRET', 'duka-dev-jwt-secret-change-in-production')
JWT_EXPIRY_HOURS = int(os.getenv('JWT_EXPIRY_HOURS', '24'))


@dataclass
class Session:
    """Decoded session data from a JWT token."""
    user_id: int
    business_id: int
    display_name: str
    role: str  # owner, manager, accountant, viewer
    phone_hash: str = ""
    exp: int = 0
    iat: int = 0
    jti: str = ""

    def is_expired(self) -> bool:
        return self.exp > 0 and time.time() > self.exp

    @property
    def is_authenticated(self) -> bool:
        return self.user_id > 0 and not self.is_expired()


def _base64url_encode(data: bytes) -> str:
    """URL-safe base64 encoding without padding."""
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _base64url_decode(data: str) -> bytes:
    """URL-safe base64 decoding with padding restoration."""
    import base64
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data)


def create_session(
    user_id: int,
    business_id: int,
    display_name: str,
    role: str = 'owner',
    phone_hash: str = "",
) -> str:
    """Create a signed JWT session token.

    Returns the JWT string (header.payload.signature).
    """
    now = int(time.time())
    exp = now + (JWT_EXPIRY_HOURS * 3600)
    jti = _generate_jti(user_id, now)

    header = {"alg": "HS256", "typ": "JWT"}

    payload = {
        "sub": str(user_id),
        "bid": business_id,
        "name": display_name,
        "role": role,
        "ph": phone_hash,
        "iat": now,
        "exp": exp,
        "jti": jti,
    }

    header_b64 = _base64url_encode(json.dumps(header, separators=(',', ':')).encode())
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(',', ':')).encode())

    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        JWT_SECRET.encode(),
        signing_input.encode(),
        hashlib.sha256
    ).digest()
    sig_b64 = _base64url_encode(signature)

    return f"{signing_input}.{sig_b64}"


def decode_session(token: str) -> Optional[Session]:
    """Decode and validate a JWT session token.

    Returns a Session object or None if invalid/expired.
    """
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"

        # Verify signature
        expected_sig = hmac.new(
            JWT_SECRET.encode(),
            signing_input.encode(),
            hashlib.sha256
        ).digest()

        actual_sig = _base64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        # Decode payload
        payload_bytes = _base64url_decode(payload_b64)
        payload = json.loads(payload_bytes)

        session = Session(
            user_id=int(payload.get("sub", 0)),
            business_id=int(payload.get("bid", 0)),
            display_name=payload.get("name", ""),
            role=payload.get("role", "viewer"),
            phone_hash=payload.get("ph", ""),
            exp=payload.get("exp", 0),
            iat=payload.get("iat", 0),
            jti=payload.get("jti", ""),
        )

        if session.is_expired():
            return None

        return session

    except (json.JSONDecodeError, ValueError, KeyError):
        return None


def persist_session(db_path: str, session: Session, token: str,
                    ip_address: str = "127.0.0.1", user_agent: str = "") -> bool:
    """Store session in authentication_session table for revocation tracking."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.utcfromtimestamp(session.exp).strftime('%Y-%m-%dT%H:%M:%SZ')
    issued_at = datetime.utcfromtimestamp(session.iat).strftime('%Y-%m-%dT%H:%M:%SZ')

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            ph = session.phone_hash if session.phone_hash else None
            conn.execute(
                """INSERT INTO authentication_session
                   (user_id, phone_hash, business_id, jwt_token_hash, ip_address, user_agent,
                    issued_at, expires_at, last_activity_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session.user_id, ph, session.business_id, token_hash,
                 ip_address, user_agent, issued_at, expires_at, issued_at)
            )
            conn.commit()
        return True
    except sqlite3.OperationalError:
        return False


def revoke_session(db_path: str, token: str, reason: str = 'logout') -> bool:
    """Revoke a session by marking it in the DB."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """UPDATE authentication_session
                   SET revoked_at = ?, revoke_reason = ?
                   WHERE jwt_token_hash = ? AND revoked_at IS NULL""",
                (now, reason, token_hash)
            )
            conn.commit()
        return True
    except sqlite3.OperationalError:
        return False


def is_session_revoked(db_path: str, token: str) -> bool:
    """Check if a session has been revoked."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.execute(
                """SELECT 1 FROM authentication_session
                   WHERE jwt_token_hash = ? AND revoked_at IS NOT NULL""",
                (token_hash,)
            )
            return cursor.fetchone() is not None
    except sqlite3.OperationalError:
        return False


def log_audit(db_path: str, event_type: str, user_id: int = None,
              phone_hash: str = None, ip_address: str = "127.0.0.1",
              details: str = None) -> bool:
    """Log an authentication event to audit_login."""
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """INSERT INTO audit_login
                   (user_id, phone_hash, event_type, ip_address, details, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, phone_hash, event_type, ip_address, details, now)
            )
            conn.commit()
        return True
    except sqlite3.OperationalError:
        return False


def _generate_jti(user_id: int, timestamp: int) -> str:
    """Generate a unique JWT ID."""
    raw = f"{user_id}:{timestamp}:{os.urandom(8).hex()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def revoke_jti(db_path: str, session: Session, reason: str = "logout") -> bool:
    """Revoke a session by its JWT id, so the token is refused from now on
    even if someone copied it before logout."""
    from db.migrate import ensure_006
    if not session.jti:
        return False
    try:
        ensure_006(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO revoked_session (jti, user_id, reason) VALUES (?, ?, ?)",
                (session.jti, session.user_id, reason),
            )
        return True
    except sqlite3.Error:
        return False


def is_jti_revoked(db_path: str, session: Session) -> bool:
    """True when this token's session was logged out."""
    if not session.jti:
        return False
    try:
        with sqlite3.connect(db_path) as conn:
            return conn.execute(
                "SELECT 1 FROM revoked_session WHERE jti = ?", (session.jti,)
            ).fetchone() is not None
    except sqlite3.OperationalError:
        return False
