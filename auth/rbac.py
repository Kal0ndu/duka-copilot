"""Account roles (one admin, everyone else a user) and security events.

Roles live in app_user.account_role (db/migrations/006_recurrence_and_rbac.sql):
  'user'   every account created by sign-up; sees only its own business
  'admin'  exactly one account, set from the server with scripts/set_admin.py;
           the only account that can read audit logs and security events

The database itself keeps the rules: a partial unique index allows at most
one admin, and a trigger refuses any account inserted as admin. Nothing in
the app UI can change a role.

Every check reads the role from the database, never from the session token
or page state, so a forged or stale token cannot grant admin rights.

Security events (failed logins, denied access, blocked escalation, ...) are
appended to the hash-chained audit_log with entity_type = 'security', and
record what happened, how it was detected and how it was handled.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from db.audit import AuditEvent, get_recent_events, log_event, verify_audit
from db.migrate import ensure_006

ADMIN = "admin"
USER = "user"
ROLES = (ADMIN, USER)

MAX_FAILED_LOGINS = 5
LOGIN_LOCKOUT = timedelta(minutes=15)

# Events written by the guard / approvals code that are security relevant.
GUARD_EVENT_TYPES = (
    "INPUT_BLOCKED", "FORBIDDEN_TOOL_CALL", "OUTPUT_WARNING", "PIN_REJECTED",
)

# Shown to a regular user who is refused; deliberately says nothing about
# what exists or why.
DENIED_MESSAGE = "You don't have permission to view this page."


class AccessDenied(PermissionError):
    """The account's role does not allow this operation."""


class PrivilegeEscalationBlocked(PermissionError):
    """An attempt to create a second admin or change a role was refused."""


# ---- security events ----

def log_security_event(db_path: str, event_type: str, *, outcome: str,
                       detection: str, handling: str, severity: str = "medium",
                       user_id: Optional[int] = None, business_id: Optional[int] = None,
                       resource: Optional[str] = None,
                       details: Optional[Dict[str, Any]] = None) -> Optional[int]:
    """Append one security event to the audit chain. Never raises."""
    try:
        return log_event(
            db_path, actor="guard" if outcome in ("denied", "blocked") else "system",
            event_type=event_type, business_id=business_id, decision=outcome,
            entity_type="security", entity_id=user_id,
            details={
                "severity": severity, "user_id": user_id, "resource": resource,
                "detection": detection, "handling": handling, **(details or {}),
            },
        )
    except Exception:
        return None


# ---- roles ----

def get_account_role(db_path: str, user_id: Optional[int]) -> Optional[str]:
    """The account's role from the database, or None for no such account."""
    if not user_id:
        return None
    ensure_006(db_path)
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT account_role, status FROM app_user WHERE user_id = ?", (user_id,)
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None or row[1] != "active":
        return None
    return row[0] if row[0] in ROLES else USER


def is_admin(db_path: str, user_id: Optional[int]) -> bool:
    return get_account_role(db_path, user_id) == ADMIN


def require_admin(db_path: str, user_id: Optional[int], resource: str) -> None:
    """Raise AccessDenied (and log it) unless user_id is the admin."""
    if is_admin(db_path, user_id):
        return
    log_security_event(
        db_path, "UNAUTHORIZED_ACCESS", user_id=user_id, resource=resource,
        outcome="denied", severity="medium",
        detection="admin-only resource requested by a non-admin account",
        handling="request refused with a generic message; nothing returned",
    )
    raise AccessDenied(DENIED_MESSAGE)


def assign_admin(db_path: str, user_id: int, *, transfer: bool = False) -> None:
    """Make user_id the single admin. Refused while another admin exists,
    unless transfer=True (the old admin becomes a user in the same
    transaction). Server-side only: called by scripts/set_admin.py."""
    ensure_006(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        target = conn.execute(
            "SELECT status FROM app_user WHERE user_id = ?", (user_id,)
        ).fetchone()
        if target is None or target[0] != "active":
            raise ValueError(f"No active account with user_id={user_id}.")
        current = conn.execute(
            "SELECT user_id FROM app_user WHERE account_role = 'admin'"
        ).fetchone()
        if current and current[0] != user_id:
            if not transfer:
                conn.rollback()
                log_security_event(
                    db_path, "PRIVILEGE_ESCALATION_BLOCKED", user_id=user_id, resource="role:admin",
                    outcome="blocked", severity="high",
                    detection="request to create a second admin account",
                    handling="refused; the existing admin is unchanged",
                    details={"existing_admin": current[0]},
                )
                raise PrivilegeEscalationBlocked(
                    f"User {current[0]} is already the admin. Use --transfer to hand over.")
            conn.execute("UPDATE app_user SET account_role = 'user' WHERE user_id = ?", (current[0],))
        conn.execute("UPDATE app_user SET account_role = 'admin' WHERE user_id = ?", (user_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    log_security_event(
        db_path, "ADMIN_ASSIGNED", user_id=user_id, resource="role:admin", outcome="success",
        severity="high", detection="server-side admin assignment",
        handling="role updated", details={"previous_admin": current[0] if current else None},
    )


# ---- login protection ----

def failed_logins_since(db_path: str, user_id: int, since: datetime) -> int:
    try:
        with sqlite3.connect(db_path) as conn:
            return conn.execute(
                """SELECT COUNT(*) FROM audit_log
                   WHERE event_type = 'LOGIN_FAILED' AND entity_type = 'security'
                     AND entity_id = ? AND ts >= ?""",
                (user_id, since.strftime("%Y-%m-%dT%H:%M:%SZ")),
            ).fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def login_locked(db_path: str, user_id: int, now: Optional[datetime] = None) -> bool:
    """True after MAX_FAILED_LOGINS failures within LOGIN_LOCKOUT."""
    now = now or datetime.utcnow()
    return failed_logins_since(db_path, user_id, now - LOGIN_LOCKOUT) >= MAX_FAILED_LOGINS


# ---- admin-only reads ----

def _event_dict(e: AuditEvent) -> Dict[str, Any]:
    return {
        "seq": e.seq, "ts": e.ts, "business_id": e.business_id, "actor": e.actor,
        "event_type": e.event_type, "tool": e.tool, "decision": e.decision,
        "entity_type": e.entity_type, "entity_id": e.entity_id, "details": e.details,
        "prev_hash": e.prev_hash, "hash": e.hash,
    }


class AdminAuditService:
    """Audit and security data. Every method checks, against the database,
    that the caller is the admin before reading anything."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def recent_events(self, requester_id: Optional[int], limit: int = 100,
                      business_id: Optional[int] = None) -> List[Dict[str, Any]]:
        require_admin(self.db_path, requester_id, "audit_log")
        return [_event_dict(e) for e in get_recent_events(self.db_path, business_id, limit)]

    def security_events(self, requester_id: Optional[int], limit: int = 200) -> List[Dict[str, Any]]:
        require_admin(self.db_path, requester_id, "security_events")
        marks = ",".join("?" * len(GUARD_EVENT_TYPES))
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""SELECT * FROM audit_log
                    WHERE entity_type = 'security' OR event_type IN ({marks})
                    ORDER BY seq DESC LIMIT ?""",
                (*GUARD_EVENT_TYPES, limit),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["details"] = json.loads(d.pop("details_json") or "{}")
            except json.JSONDecodeError:
                d["details"] = {}
            out.append(d)
        return out

    def summary(self, requester_id: Optional[int]) -> List[Dict[str, Any]]:
        require_admin(self.db_path, requester_id, "security_summary")
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT event_type, COALESCE(decision, 'n/a'), COUNT(*), MAX(ts)
                   FROM audit_log GROUP BY 1, 2 ORDER BY 3 DESC"""
            ).fetchall()
        return [{"event_type": a, "decision": b, "count": c, "last_seen": d} for a, b, c, d in rows]

    def verify_chain(self, requester_id: Optional[int]) -> Dict[str, Any]:
        require_admin(self.db_path, requester_id, "audit_chain")
        return verify_audit(self.db_path)

    def accounts(self, requester_id: Optional[int]) -> List[Dict[str, Any]]:
        require_admin(self.db_path, requester_id, "accounts")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT user_id, display_name, account_role, status, created_at, last_login_at
                   FROM app_user ORDER BY user_id"""
            ).fetchall()
        return [dict(r) for r in rows]
