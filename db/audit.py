"""Append-only, hash-chained audit log: write events, verify chain integrity."""
import sqlite3
import json
import hashlib
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

GENESIS = "GENESIS"


@dataclass
class AuditEvent:
    seq: int
    ts: str
    business_id: Optional[int]
    actor: str
    event_type: str
    tool: Optional[str]
    tier: Optional[str]
    decision: Optional[str]
    entity_type: Optional[str]
    entity_id: Optional[int]
    details: Dict[str, Any]
    prev_hash: str
    hash: str


def _compute_hash(prev_hash: str, ts: str, business_id: Optional[int], actor: str,
                   event_type: str, tool: Optional[str], tier: Optional[str],
                   decision: Optional[str], entity_type: Optional[str],
                   entity_id: Optional[int], details_json: str) -> str:
    """Deterministic SHA-256 over the entry's fields, chained to prev_hash."""
    payload = "|".join(str(x) for x in (
        prev_hash, ts, business_id, actor, event_type, tool, tier,
        decision, entity_type, entity_id, details_json,
    ))
    return hashlib.sha256(payload.encode()).hexdigest()


def log_event(db_path: str, actor: str, event_type: str, *,
              business_id: Optional[int] = None, tool: Optional[str] = None,
              tier: Optional[str] = None, decision: Optional[str] = None,
              entity_type: Optional[str] = None, entity_id: Optional[int] = None,
              details: Optional[Dict[str, Any]] = None) -> Optional[int]:
    """Append one event to the hash-chained audit_log table. Returns seq, or None on failure.

    actor must be one of 'agent','owner','guard','system' (table CHECK constraint).
    """
    ts = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    details_json = json.dumps(details or {}, default=str, sort_keys=True)

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            row = conn.execute("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
            prev_hash = row[0] if row else GENESIS

            new_hash = _compute_hash(
                prev_hash, ts, business_id, actor, event_type, tool, tier,
                decision, entity_type, entity_id, details_json,
            )

            cursor = conn.execute(
                """INSERT INTO audit_log
                   (ts, business_id, actor, event_type, tool, tier, decision,
                    entity_type, entity_id, details_json, prev_hash, hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, business_id, actor, event_type, tool, tier, decision,
                 entity_type, entity_id, details_json, prev_hash, new_hash),
            )
            conn.commit()
            return cursor.lastrowid
    except sqlite3.Error:
        return None


def get_recent_events(db_path: str, business_id: Optional[int] = None,
                       limit: int = 25) -> List[AuditEvent]:
    """Return the most recent audit events, newest first."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if business_id is not None:
                rows = conn.execute(
                    """SELECT * FROM audit_log WHERE business_id = ?
                       ORDER BY seq DESC LIMIT ?""",
                    (business_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_log ORDER BY seq DESC LIMIT ?", (limit,)
                ).fetchall()
    except sqlite3.Error:
        return []

    events = []
    for r in rows:
        try:
            details = json.loads(r["details_json"]) if r["details_json"] else {}
        except json.JSONDecodeError:
            details = {}
        events.append(AuditEvent(
            seq=r["seq"], ts=r["ts"], business_id=r["business_id"], actor=r["actor"],
            event_type=r["event_type"], tool=r["tool"], tier=r["tier"],
            decision=r["decision"], entity_type=r["entity_type"], entity_id=r["entity_id"],
            details=details, prev_hash=r["prev_hash"], hash=r["hash"],
        ))
    return events


def verify_audit(db_path: str) -> Dict[str, Any]:
    """Walk the whole audit_log chain and recompute hashes to confirm no tampering.

    Returns {valid, checked, first_break_seq}. An empty log is valid by definition.
    """
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM audit_log ORDER BY seq ASC").fetchall()
    except sqlite3.Error as e:
        return {"valid": False, "checked": 0, "first_break_seq": None, "error": str(e)}

    expected_prev = GENESIS
    for r in rows:
        if r["prev_hash"] != expected_prev:
            return {"valid": False, "checked": r["seq"], "first_break_seq": r["seq"]}

        recomputed = _compute_hash(
            r["prev_hash"], r["ts"], r["business_id"], r["actor"], r["event_type"],
            r["tool"], r["tier"], r["decision"], r["entity_type"], r["entity_id"],
            r["details_json"],
        )
        if recomputed != r["hash"]:
            return {"valid": False, "checked": r["seq"], "first_break_seq": r["seq"]}

        expected_prev = r["hash"]

    return {"valid": True, "checked": len(rows), "first_break_seq": None}
