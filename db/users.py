"""User CRUD operations for the Duka auth system."""
import sqlite3
from datetime import datetime
from typing import Optional
from dataclasses import dataclass


@dataclass
class UserRecord:
    user_id: int
    phone_hash: str
    display_name: str
    phone_verified: bool
    email_hash: Optional[str] = None
    email_verified: bool = False
    status: str = 'active'
    last_login_at: Optional[str] = None
    created_at: Optional[str] = None


def create_user(db_path: str, phone_hash: str, display_name: str,
                password_hash: Optional[str] = None,
                password_salt: Optional[str] = None,
                email_hash: Optional[str] = None) -> Optional[int]:
    """Create a new user. Returns user_id or None on failure."""
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.execute(
                """INSERT INTO app_user
                   (phone_hash, phone_verified, email_hash, display_name,
                    password_hash, password_salt, display_token, status, created_at, updated_at)
                   VALUES (?, 0, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (phone_hash, email_hash, display_name,
                 password_hash, password_salt, display_name, now, now)
            )
            conn.commit()
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None  # Phone hash already exists


def get_user_by_phone(db_path: str, phone_hash: str) -> Optional[UserRecord]:
    """Look up a user by phone hash."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT user_id, phone_hash, phone_verified, email_hash,
                          email_verified, display_name, status, last_login_at, created_at
                   FROM app_user WHERE phone_hash = ?""",
                (phone_hash,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return UserRecord(
                user_id=row['user_id'],
                phone_hash=row['phone_hash'],
                display_name=row['display_name'],
                phone_verified=bool(row['phone_verified']),
                email_hash=row['email_hash'],
                email_verified=bool(row['email_verified']),
                status=row['status'],
                last_login_at=row['last_login_at'],
                created_at=row['created_at'],
            )
    except sqlite3.OperationalError:
        return None


def get_user_by_id(db_path: str, user_id: int) -> Optional[UserRecord]:
    """Look up a user by ID."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT user_id, phone_hash, phone_verified, email_hash,
                          email_verified, display_name, status, last_login_at, created_at
                   FROM app_user WHERE user_id = ?""",
                (user_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return UserRecord(
                user_id=row['user_id'],
                phone_hash=row['phone_hash'],
                display_name=row['display_name'],
                phone_verified=bool(row['phone_verified']),
                email_hash=row['email_hash'],
                email_verified=bool(row['email_verified']),
                status=row['status'],
                last_login_at=row['last_login_at'],
                created_at=row['created_at'],
            )
    except sqlite3.OperationalError:
        return None


def get_user_password(db_path: str, user_id: int) -> tuple:
    """Return (password_hash, password_salt) for a user."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.execute(
                "SELECT password_hash, password_salt FROM app_user WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                return (row[0] or "", row[1] or "")
            return ("", "")
    except sqlite3.OperationalError:
        return ("", "")


def update_password(db_path: str, user_id: int, password_hash: str,
                    password_salt: str) -> bool:
    """Update a user's password."""
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """UPDATE app_user
                   SET password_hash = ?, password_salt = ?, updated_at = ?
                   WHERE user_id = ?""",
                (password_hash, password_salt, now, user_id)
            )
            conn.commit()
        return True
    except sqlite3.OperationalError:
        return False


def mark_phone_verified(db_path: str, user_id: int) -> bool:
    """Mark a user's phone as verified."""
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """UPDATE app_user
                   SET phone_verified = 1, updated_at = ?
                   WHERE user_id = ?""",
                (now, user_id)
            )
            conn.commit()
        return True
    except sqlite3.OperationalError:
        return False


def update_last_login(db_path: str, user_id: int, ip_address: str = "127.0.0.1") -> bool:
    """Update last login timestamp and IP."""
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """UPDATE app_user
                   SET last_login_at = ?, last_login_ip = ?, updated_at = ?
                   WHERE user_id = ?""",
                (now, ip_address, now, user_id)
            )
            conn.commit()
        return True
    except sqlite3.OperationalError:
        return False
