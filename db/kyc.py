"""KYC profile database operations."""
import sqlite3
from datetime import datetime
from typing import Optional
from dataclasses import dataclass


@dataclass
class KycProfile:
    kyc_id: int
    user_id: int
    status: str  # pending, verified, flagged
    national_id_number_hash: Optional[str] = None
    national_id_verified_at: Optional[str] = None
    physical_address: Optional[str] = None
    postal_code: Optional[str] = None
    business_registration_number: Optional[str] = None
    sanctions_result: Optional[str] = None
    verified_at: Optional[str] = None
    created_at: Optional[str] = None


def create_kyc_profile(db_path: str, user_id: int,
                       national_id_number_hash: Optional[str] = None,
                       physical_address: Optional[str] = None,
                       postal_code: Optional[str] = None,
                       business_registration_number: Optional[str] = None
                       ) -> Optional[int]:
    """Create a KYC profile for a user. Returns kyc_id or None."""
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.execute(
                """INSERT OR IGNORE INTO kyc_profile
                   (user_id, status, national_id_number_hash, physical_address,
                    postal_code, business_registration_number, created_at)
                   VALUES (?, 'pending', ?, ?, ?, ?, ?)""",
                (user_id, national_id_number_hash, physical_address,
                 postal_code, business_registration_number, now)
            )
            conn.commit()
            return cursor.lastrowid
    except sqlite3.OperationalError:
        return None


def get_kyc_profile(db_path: str, user_id: int) -> Optional[KycProfile]:
    """Get KYC profile for a user."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT kyc_id, user_id, status, national_id_number_hash,
                          national_id_verified_at, physical_address, postal_code,
                          business_registration_number, sanctions_result,
                          verified_at, created_at
                   FROM kyc_profile WHERE user_id = ?""",
                (user_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return KycProfile(
                kyc_id=row['kyc_id'],
                user_id=row['user_id'],
                status=row['status'],
                national_id_number_hash=row['national_id_number_hash'],
                national_id_verified_at=row['national_id_verified_at'],
                physical_address=row['physical_address'],
                postal_code=row['postal_code'],
                business_registration_number=row['business_registration_number'],
                sanctions_result=row['sanctions_result'],
                verified_at=row['verified_at'],
                created_at=row['created_at'],
            )
    except sqlite3.OperationalError:
        return None


def update_kyc_status(db_path: str, user_id: int, status: str,
                      verified_at: Optional[str] = None) -> bool:
    """Update KYC status for a user."""
    now = verified_at or datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """UPDATE kyc_profile
                   SET status = ?, verified_at = ?
                   WHERE user_id = ?""",
                (status, now, user_id)
            )
            conn.commit()
        return True
    except sqlite3.OperationalError:
        return False
