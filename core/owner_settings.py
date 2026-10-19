"""Each business's own rules, controlled by the OWNER (never the AI).

Stored in business_settings (db/migrations/005_owner_settings_and_pin.sql):
  per_txn_cap_minor, daily_cap_minor   payment caps the guard enforces
  loan_cap_minor                       biggest loan the AI may propose
  safety_buffer_minor                  forecast alerts fire below this
  payday_weekday                       staff payday (0=Mon), or None
  language                             'en' or 'sw' for the copilot's replies
Verified payees are rows in payee (verified = 1).

Changing caps or payees needs the owner PIN (see needs_pin / OwnerPin).
A business with no saved row uses the defaults from .env (core.config).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from core.config import Config

MIGRATION = Path(__file__).resolve().parents[1] / "db" / "migrations" / "005_owner_settings_and_pin.sql"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DEFAULT_LOAN_CAP_MINOR = 5_000_000          # KES 50,000
SENSITIVE = ("per_txn_cap_minor", "daily_cap_minor", "loan_cap_minor")
MAX_WRONG_PINS = 3
LOCKOUT = timedelta(minutes=15)
PIN_FORMAT = re.compile(r"^\d{4,6}$")


class PinError(Exception):
    pass


@dataclass
class OwnerSettings:
    business_id: int
    per_txn_cap_minor: int
    daily_cap_minor: int
    loan_cap_minor: int
    safety_buffer_minor: int
    payday_weekday: Optional[int] = None
    language: str = "en"

    def to_dict(self) -> dict:
        return asdict(self)


_SCHEMA_READY: set = set()


def ensure_schema(db_path: str) -> None:
    """Create the 005 tables if missing. Runs its checks once per database
    per process and only writes when something is missing, so it never
    contends with an open write (e.g. an upload in progress)."""
    if db_path in _SCHEMA_READY:
        return
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not {"business_settings", "owner_pin"} <= tables:
            conn.executescript(MIGRATION.read_text(encoding="utf-8"))
        # Approval requests notify through the standing-orders notification
        # table; this links a notification to the request it is about.
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "notification" in tables:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(notification)")}
            if "action_id" not in cols:
                conn.execute("ALTER TABLE notification ADD COLUMN action_id INTEGER "
                             "REFERENCES proposed_action(action_id)")
    _SCHEMA_READY.add(db_path)


def defaults(business_id: int) -> OwnerSettings:
    return OwnerSettings(
        business_id=business_id,
        per_txn_cap_minor=Config.CAP_PER_TXN,
        daily_cap_minor=Config.CAP_DAILY,
        loan_cap_minor=DEFAULT_LOAN_CAP_MINOR,
        safety_buffer_minor=Config.SAFETY_BUFFER_MINOR,
    )


def load_settings(db_path: str, business_id: int) -> OwnerSettings:
    ensure_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM business_settings WHERE business_id = ?", (business_id,)
        ).fetchone()
    if row is None:
        return defaults(business_id)
    return OwnerSettings(
        business_id=business_id,
        per_txn_cap_minor=row["per_txn_cap_minor"],
        daily_cap_minor=row["daily_cap_minor"],
        loan_cap_minor=row["loan_cap_minor"],
        safety_buffer_minor=row["safety_buffer_minor"],
        payday_weekday=row["payday_weekday"],
        language=row["language"],
    )


def validate(s: OwnerSettings) -> List[str]:
    """A list of problems (empty = fine)."""
    problems = []
    for key in SENSITIVE:
        if not isinstance(getattr(s, key), int) or getattr(s, key) <= 0:
            problems.append(f"{key} must be a positive amount")
    if not problems and s.daily_cap_minor < s.per_txn_cap_minor:
        problems.append("the daily cap can't be smaller than the per-payment cap")
    if s.safety_buffer_minor < 0:
        problems.append("the safety buffer must be 0 or more")
    if s.payday_weekday is not None and s.payday_weekday not in range(7):
        problems.append("payday must be a weekday (0=Mon .. 6=Sun) or empty")
    if s.language not in ("en", "sw"):
        problems.append("language must be 'en' or 'sw'")
    return problems


def changes(old: OwnerSettings, new: OwnerSettings) -> Dict[str, tuple]:
    o, n = old.to_dict(), new.to_dict()
    return {k: (o[k], n[k]) for k in n if o[k] != n[k]}


def needs_pin(old: OwnerSettings, new: OwnerSettings) -> bool:
    """Changing any cap needs the owner PIN."""
    return any(k in SENSITIVE for k in changes(old, new))


def save_settings(db_path: str, new: OwnerSettings, user_id: Optional[int] = None,
                  pin: Optional[str] = None) -> Dict[str, tuple]:
    """Validate and save. Raises ValueError on bad values and PinError when
    a cap changes without the correct PIN. Returns what changed."""
    problems = validate(new)
    if problems:
        raise ValueError("; ".join(problems))
    old = load_settings(db_path, new.business_id)
    if needs_pin(old, new):
        OwnerPin(db_path).verify(new.business_id, pin)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO business_settings
               (business_id, per_txn_cap_minor, daily_cap_minor, loan_cap_minor,
                safety_buffer_minor, payday_weekday, language, updated_by_user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (business_id) DO UPDATE SET
                 per_txn_cap_minor = excluded.per_txn_cap_minor,
                 daily_cap_minor = excluded.daily_cap_minor,
                 loan_cap_minor = excluded.loan_cap_minor,
                 safety_buffer_minor = excluded.safety_buffer_minor,
                 payday_weekday = excluded.payday_weekday,
                 language = excluded.language,
                 updated_by_user_id = excluded.updated_by_user_id,
                 updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
            (new.business_id, new.per_txn_cap_minor, new.daily_cap_minor, new.loan_cap_minor,
             new.safety_buffer_minor, new.payday_weekday, new.language, user_id),
        )
    diff = changes(old, new)
    if diff:
        from db.audit import log_event
        log_event(db_path, "owner", "SETTINGS_CHANGED", business_id=new.business_id,
                  decision="saved", details={k: list(v) for k, v in diff.items()})
    return diff


# ---- verified payees ----

def list_payees(db_path: str, business_id: int, verified_only: bool = True) -> List[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""SELECT payee_id, label_token AS name, verified, per_txn_cap_minor, active
                FROM payee WHERE business_id = ? AND active = 1
                {"AND verified = 1" if verified_only else ""} ORDER BY payee_id""",
            (business_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_payee(db_path: str, business_id: int, name: str, pin: str,
              kind: str = "supplier", user_id: Optional[int] = None) -> int:
    """Owner adds a verified payee (PIN required). Returns payee_id."""
    name = " ".join(str(name).split()).upper()
    if not name or len(name) > 40:
        raise ValueError("Payee name must be 1-40 characters.")
    OwnerPin(db_path).verify(business_id, pin)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        if conn.execute(
            "SELECT 1 FROM payee WHERE business_id = ? AND active = 1 AND UPPER(label_token) = ?",
            (business_id, name),
        ).fetchone():
            raise ValueError(f"{name} is already on your payee list.")
        token = "PAYEE_" + hashlib.sha256(f"{business_id}:{name}".encode()).hexdigest()[:10].upper()
        conn.execute(
            """INSERT INTO party (business_id, kind, display_token, is_business_related)
               VALUES (?, ?, ?, 1)
               ON CONFLICT (business_id, display_token) DO NOTHING""",
            (business_id, kind, token),
        )
        party_id = conn.execute(
            "SELECT party_id FROM party WHERE business_id = ? AND display_token = ?",
            (business_id, token),
        ).fetchone()[0]
        payee_id = conn.execute(
            """INSERT INTO payee (business_id, party_id, label_token, verified, verified_by, verified_at)
               VALUES (?, ?, ?, 1, 'owner', strftime('%Y-%m-%dT%H:%M:%SZ','now'))""",
            (business_id, party_id, name),
        ).lastrowid
    from db.audit import log_event
    log_event(db_path, "owner", "PAYEE_ADDED", business_id=business_id, entity_type="payee",
              entity_id=payee_id, decision="saved", details={"name": name, "by_user": user_id})
    return payee_id


def remove_payee(db_path: str, business_id: int, payee_id: int, pin: str) -> None:
    OwnerPin(db_path).verify(business_id, pin)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE payee SET active = 0 WHERE payee_id = ? AND business_id = ?",
                     (payee_id, business_id))
    from db.audit import log_event
    log_event(db_path, "owner", "PAYEE_REMOVED", business_id=business_id, entity_type="payee",
              entity_id=payee_id, decision="saved")


# ---- the owner's PIN ----

class OwnerPin:
    """PBKDF2-hashed PIN per business, with a lockout after 3 wrong tries.
    The AI never has a tool that calls any of this."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or Config.DB_PATH
        ensure_schema(self.db_path)

    @staticmethod
    def _hash(pin: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac("sha256", str(pin).encode(), bytes.fromhex(salt), 100_000).hex()

    def is_set(self, business_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                "SELECT 1 FROM owner_pin WHERE business_id = ?", (business_id,)
            ).fetchone() is not None

    def set_pin(self, business_id: int, new_pin: str, current_pin: Optional[str] = None) -> None:
        """First time: no current PIN needed. After that: the current PIN is."""
        if not PIN_FORMAT.match(str(new_pin or "")):
            raise PinError("The PIN must be 4 to 6 digits.")
        if self.is_set(business_id):
            self.verify(business_id, current_pin)
        salt = secrets.token_hex(16)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO owner_pin (business_id, pin_hash, pin_salt) VALUES (?, ?, ?)
                   ON CONFLICT (business_id) DO UPDATE SET pin_hash = excluded.pin_hash,
                     pin_salt = excluded.pin_salt, failed_attempts = 0, locked_until = NULL,
                     updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
                (business_id, self._hash(new_pin, salt), salt),
            )
        from db.audit import log_event
        log_event(self.db_path, "owner", "PIN_SET", business_id=business_id, decision="saved")

    def verify(self, business_id: int, pin: Optional[str], now: Optional[datetime] = None) -> None:
        """Raise PinError unless pin is right. Wrong PINs count towards a lockout."""
        now = now or datetime.utcnow()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT pin_hash, pin_salt, failed_attempts, locked_until FROM owner_pin WHERE business_id = ?",
                (business_id,),
            ).fetchone()
            if row is None:
                raise PinError("Set your owner PIN in Business Setup first.")
            pin_hash, salt, failed, locked_until = row
            if locked_until and now < datetime.fromisoformat(locked_until):
                raise PinError("Approvals are locked after too many wrong PINs. Try again later.")
            if pin is not None and hmac.compare_digest(self._hash(pin, salt), pin_hash):
                conn.execute(
                    "UPDATE owner_pin SET failed_attempts = 0, locked_until = NULL WHERE business_id = ?",
                    (business_id,),
                )
                return
            failed += 1
            lock = (now + LOCKOUT).isoformat() if failed >= MAX_WRONG_PINS else None
            conn.execute(
                "UPDATE owner_pin SET failed_attempts = ?, locked_until = ? WHERE business_id = ?",
                (0 if lock else failed, lock, business_id),
            )
        from db.audit import log_event
        log_event(self.db_path, "guard", "PIN_REJECTED", business_id=business_id,
                  decision="blocked", details={"locked": bool(lock)})
        if lock:
            raise PinError("Wrong PIN. Approvals are now locked for 15 minutes.")
        raise PinError(f"Wrong PIN ({failed} of {MAX_WRONG_PINS}).")
