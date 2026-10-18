"""Session & business-member database queries."""
import sqlite3
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class BusinessMember:
    member_id: int
    business_id: int
    user_id: int
    role: str
    is_active: bool
    display_name: str = ""
    business_name_token: str = ""


def get_user_businesses(db_path: str, user_id: int) -> List[BusinessMember]:
    """Get all business memberships for a user."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT bm.member_id, bm.business_id, bm.user_id, bm.role,
                          bm.is_active, b.name_token as business_name_token
                   FROM business_member bm
                   JOIN business b ON bm.business_id = b.business_id
                   WHERE bm.user_id = ? AND bm.is_active = 1
                   ORDER BY bm.added_at""",
                (user_id,)
            )
            return [
                BusinessMember(
                    member_id=row['member_id'],
                    business_id=row['business_id'],
                    user_id=row['user_id'],
                    role=row['role'],
                    is_active=bool(row['is_active']),
                    business_name_token=row['business_name_token'],
                )
                for row in cursor.fetchall()
            ]
    except sqlite3.OperationalError:
        return []


def add_business_member(db_path: str, business_id: int, user_id: int,
                        role: str = 'owner') -> Optional[int]:
    """Add a user to a business with a role. Returns member_id or None."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.execute(
                """INSERT OR IGNORE INTO business_member
                   (business_id, user_id, role, is_active)
                   VALUES (?, ?, ?, 1)""",
                (business_id, user_id, role)
            )
            conn.commit()
            if cursor.lastrowid:
                return cursor.lastrowid
            # Already exists — get existing
            cursor2 = conn.execute(
                """SELECT member_id FROM business_member
                   WHERE business_id = ? AND user_id = ?""",
                (business_id, user_id)
            )
            row = cursor2.fetchone()
            return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def get_user_role(db_path: str, user_id: int, business_id: int) -> Optional[str]:
    """Get a user's role in a specific business."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.execute(
                """SELECT role FROM business_member
                   WHERE user_id = ? AND business_id = ? AND is_active = 1""",
                (user_id, business_id)
            )
            row = cursor.fetchone()
            return row[0] if row else None
    except sqlite3.OperationalError:
        return None
