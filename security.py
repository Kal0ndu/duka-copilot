"""
security.py - Step 7: the safety layer between the AI and the money
=====================================================================

  1. PolicyGuard - checks every action against permission tiers:
       T0 read        -> allowed
       T1 suggest     -> allowed (nothing moves)
       T2 execute     -> allowed only with the owner's approval, a verified payee,
                         and within the per-payment and daily caps
       T3 forbidden   -> always refused, and so is anything not on the list
  2. Approvals   - only the owner, with their PIN in the app, can approve. The
                   approval code is tied to one exact action, works once, expires.
  3. Redactor    - hides phone numbers and names before text reaches the AI
  4. AuditLog    - append-only log; each entry holds the hash of the previous one,
                   so changing or deleting an old entry is detected

See sandbox.py for where approved actions are carried out, and for the demo.
"""

import hashlib
import hmac
import json
import math
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. PERMISSION TIERS AND THE POLICY GUARD
# ---------------------------------------------------------------------------

T0, T1, T2, T3 = "T0 read", "T1 suggest", "T2 execute", "T3 forbidden"

# Every action the AI may ask for: its tier and the exact fields it must have.
ACTIONS = {
    "read_summary":    {"tier": T0, "fields": {}},
    "read_forecast":   {"tier": T0, "fields": {}},
    "compare_credit":  {"tier": T0, "fields": {"amount": "money", "term_days": "days"}},
    "suggest_payment": {"tier": T1, "fields": {"payee_id": "text", "amount": "money"}},
    "pay_supplier":    {"tier": T2, "fields": {"payee_id": "text", "amount": "money"}},
    "request_loan":    {"tier": T2, "fields": {"product": "text", "amount": "money",
                                               "term_days": "days"}},
}

# Never allowed, whatever reason is given. Unlisted actions are refused too.
FORBIDDEN = {
    "approve_request": "only the owner can approve, with their PIN in the app",
    "raise_limit": "limits can only be changed by the owner, outside the AI",
    "change_policy": "the rules can only be changed by the owner, outside the AI",
    "add_payee": "new payees must be checked and added by the owner",
    "send_data_external": "the owner's data never leaves the app",
}


@dataclass
class Policy:
    """The owner's rules. Only the owner changes these, never the AI."""
    verified_payees: dict           # payee_id -> name, checked by the owner
    per_transaction_cap: float      # biggest single payment (KES)
    daily_cap: float                # most that can be paid out in one day (KES)
    loan_cap: float                 # biggest loan the AI may ask for (KES)
    loan_products: tuple            # lenders' products the AI may ask for
    max_term_days: int = 365


# Amina's settings: her real regular payees, and caps that fit her
# KES ~30,000 stock purchases.
AMINA_POLICY = Policy(
    verified_payees={
        "SUP-01": "SOKO SUPPLIES",
        "SUP-02": "FRESHFARM WHOLESALERS",
        "SUP-03": "UNGA DISTRIBUTORS LTD",
        "RENT-01": "MWANGI PROPERTIES",
        "UTIL-01": "POWER CO TOKENS",
    },
    per_transaction_cap=35_000,
    daily_cap=60_000,
    loan_cap=60_000,
    loan_products=("sacco", "bank", "micro_loan"),
)


@dataclass
class Decision:
    allowed: bool
    tier: str
    needs_approval: bool
    reason: str


def short(value, limit=40):
    """Quote a value safely in a message (long text could hide instructions)."""
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "...'"


class PolicyGuard:
    def __init__(self, policy):
        self.policy = policy

    def check(self, action, spent_today=0.0):
        """Decide whether an action may go ahead. `spent_today` is what has
        already been paid out today (from the account, not from the AI)."""
        if not isinstance(action, dict) or not isinstance(action.get("type"), str):
            return Decision(False, T3, False, "not a valid action")
        kind = action["type"]
        if kind in FORBIDDEN:
            return Decision(False, T3, False, f"forbidden: {FORBIDDEN[kind]}")
        if kind not in ACTIONS:
            return Decision(False, T3, False,
                            f"unknown action {short(kind)}: only listed actions are allowed")

        tier = ACTIONS[kind]["tier"]
        problem = (self._check_fields(action, ACTIONS[kind]["fields"])
                   or self._check_limits(kind, action, spent_today))
        if problem:
            return Decision(False, tier, False, problem)
        if tier == T2:
            return Decision(True, tier, True, "allowed once the owner approves")
        return Decision(True, tier, False, "allowed")

    def _check_fields(self, action, fields):
        """The action must have exactly the right fields, with sensible values."""
        given = set(action) - {"type"}
        if given != set(fields):
            extra, missing = sorted(given - set(fields)), sorted(set(fields) - given)
            return f"malformed: unexpected fields {extra}, missing fields {missing}"
        for name, kind in fields.items():
            value = action[name]
            is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if kind == "money":
                ok = is_number and math.isfinite(value) and value > 0
            elif kind == "days":
                ok = isinstance(value, int) and not isinstance(value, bool) \
                     and 1 <= value <= self.policy.max_term_days
            else:
                ok = isinstance(value, str)
            if not ok:
                return f"malformed: bad value for '{name}': {short(value)}"
        return None

    def _check_limits(self, kind, action, spent_today):
        p = self.policy
        if kind in ("pay_supplier", "suggest_payment"):
            if action["payee_id"] not in p.verified_payees:
                return (f"payee {short(action['payee_id'])} is not on the owner's "
                        f"verified list")
        if kind == "pay_supplier":
            amount = action["amount"]
            if amount > p.per_transaction_cap:
                return (f"KES {amount:,.0f} is over the per-payment cap of "
                        f"KES {p.per_transaction_cap:,.0f}")
            if spent_today + amount > p.daily_cap:
                return (f"this would bring today's payments to KES {spent_today + amount:,.0f}, "
                        f"over the daily cap of KES {p.daily_cap:,.0f}")
        if kind == "request_loan":
            if action["product"] not in p.loan_products:
                return f"loan product {short(action['product'])} is not allowed"
            if action["amount"] > p.loan_cap:
                return (f"KES {action['amount']:,.0f} is over the loan cap of "
                        f"KES {p.loan_cap:,.0f}")
        return None


# ---------------------------------------------------------------------------
# 2. OWNER APPROVALS
# The AI never gets: the PIN, the approval codes, or a tool that calls approve().
# ---------------------------------------------------------------------------

class ApprovalError(Exception):
    pass


def fingerprint(action):
    """A short unique code for an exact action (any change -> different code)."""
    return hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()


class Approvals:
    MAX_WRONG_PINS = 3
    VALID_FOR = timedelta(minutes=10)

    def __init__(self, owner_pin):
        self._salt = secrets.token_bytes(16)
        self._pin_hash = self._hash_pin(owner_pin)   # the PIN itself is not kept
        self._key = secrets.token_bytes(32)          # signs approval codes, memory only
        self._requests = {}
        self._wrong_pins = 0

    def _hash_pin(self, pin):
        return hashlib.pbkdf2_hmac("sha256", str(pin).encode(), self._salt, 100_000)

    def _sign(self, request_id, req):
        message = f"{request_id}|{req['fingerprint']}|{req['expires'].isoformat()}"
        return hmac.new(self._key, message.encode(), "sha256").hexdigest()

    def request(self, action):
        """Store a copy of the action, waiting for the owner. Returns its id."""
        request_id = "REQ-" + secrets.token_hex(4).upper()
        self._requests[request_id] = {"action": json.loads(json.dumps(action)),
                                      "fingerprint": fingerprint(action),
                                      "status": "waiting", "expires": None}
        return request_id

    def waiting_action(self, request_id):
        """What the owner's app shows before the owner decides."""
        req = self._requests.get(request_id)
        return dict(req["action"]) if req and req["status"] == "waiting" else None

    def approve(self, request_id, pin, now=None):
        """OWNER'S APP ONLY. Returns an approval code, or raises ApprovalError."""
        now = now or datetime.now()
        if self._wrong_pins >= self.MAX_WRONG_PINS:
            raise ApprovalError("approvals are locked after too many wrong PINs")
        req = self._requests.get(request_id)
        if not req or req["status"] != "waiting":
            raise ApprovalError("no such request is waiting for approval")
        if not hmac.compare_digest(self._hash_pin(pin), self._pin_hash):
            self._wrong_pins += 1
            raise ApprovalError(f"wrong PIN ({self._wrong_pins} of {self.MAX_WRONG_PINS})")
        self._wrong_pins = 0
        req["status"], req["expires"] = "approved", now + self.VALID_FOR
        return self._sign(request_id, req)

    def consume(self, request_id, code, now=None):
        """Check the approval code fits this exact request; it works only once.
        Returns the approved action (the stored copy), or raises ApprovalError."""
        now = now or datetime.now()
        req = self._requests.get(request_id)
        if not req:
            raise ApprovalError("unknown request")
        if req["status"] == "used":
            raise ApprovalError("this approval has already been used")
        if req["status"] != "approved":
            raise ApprovalError("the owner has not approved this request")
        if not isinstance(code, str) or not hmac.compare_digest(code, self._sign(request_id, req)):
            raise ApprovalError("the approval code is not valid")
        if now > req["expires"]:
            req["status"] = "expired"
            raise ApprovalError("the approval has expired")
        req["status"] = "used"
        return json.loads(json.dumps(req["action"]))


# ---------------------------------------------------------------------------
# 3. REDACTION
# ---------------------------------------------------------------------------

# Kenyan mobile numbers: 0712345678, +254712345678, 0712 345 678, 0712***678
PHONE = re.compile(r"(?<![\d*])(?:\+?254|0)[\s-]?[17](?:[\s-]?[\d*]){8}(?![\d*])")
# In statements a person's name comes right after their number and runs to the
# end of the line: "... 07xx - NAME". Everything up to the line end is hidden,
# so text smuggled into the name field (like "50,000") can't leak out.
NAME_AFTER_PHONE = re.compile(r"(\[PHONE\]\s*-\s*)([^\n]+)")


class Redactor:
    """Replaces phone numbers with [PHONE] and names with [PERSON_n]. The same
    person always gets the same label. The label list stays in the app.
    Limit: names in free text are only caught if they are in `known_names`."""

    def __init__(self, known_names=()):
        self._labels = {}
        self._known = [n for n in known_names if n.strip()]

    def _label(self, name):
        key = " ".join(name.lower().split())
        if key not in self._labels:
            self._labels[key] = f"[PERSON_{len(self._labels) + 1}]"
        return self._labels[key]

    def redact(self, text):
        text = PHONE.sub("[PHONE]", str(text))
        text = NAME_AFTER_PHONE.sub(lambda m: m.group(1) + self._label(m.group(2).strip()), text)
        for name in self._known:
            text = re.sub(rf"\b{re.escape(name)}\b", lambda m: self._label(m.group(0)),
                          text, flags=re.IGNORECASE)
        return text


# ---------------------------------------------------------------------------
# 4. APPEND-ONLY AUDIT LOG WITH A HASH CHAIN
# ---------------------------------------------------------------------------

GENESIS = "0" * 64      # the "previous hash" of the very first entry


def entry_hash(entry):
    body = {k: v for k, v in entry.items() if k != "hash"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def verify_log(path):
    """Re-check the whole chain. Returns (ok, entries checked, problem, last hash)."""
    prev, count = GENESIS, 0
    if not Path(path).exists():
        return True, 0, None, prev
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                return False, count, f"entry {n} is not valid JSON", prev
            if entry.get("seq") != n or entry.get("prev_hash") != prev:
                return False, count, (f"entry {n} does not link to entry {n - 1} "
                                      f"(an entry was removed, added or reordered)"), prev
            if entry.get("hash") != entry_hash(entry):
                return False, count, f"entry {n} was changed after it was written", prev
            prev, count = entry["hash"], n
    return True, count, None, prev


class AuditLog:
    """Entries can only be added. There is no edit or delete. The app refuses to
    start if the existing log fails the check.
    Limit: someone who rewrites the WHOLE file could rebuild the chain, so the
    latest hash (`head`) should also be kept somewhere else, e.g. sent to the
    owner by SMS each day."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ok, self.count, problem, self.head = verify_log(self.path)
        if not ok:
            raise RuntimeError(f"Audit log {self.path} has been tampered with: {problem}")

    def record(self, actor, event, **details):
        entry = {"seq": self.count + 1, "time": datetime.now().isoformat(timespec="seconds"),
                 "actor": actor, "event": event, "details": details, "prev_hash": self.head}
        entry = json.loads(json.dumps(entry, default=str))   # store exactly what we hash
        entry["hash"] = entry_hash(entry)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        self.count, self.head = entry["seq"], entry["hash"]
        return entry
