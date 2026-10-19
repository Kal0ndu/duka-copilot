"""The AI proposes; only the owner approves, with their PIN.

Flow (every step is written to the hash-chained audit log):
  1. propose_payment / propose_loan  (the AI's T2 tools)
       The payment guard checks the owner's rules. A request that breaks a
       rule is saved as BLOCKED; otherwise PENDING_APPROVAL. Nothing moves.
  2. approve(action_id, pin)          (Approvals page only, never an AI tool)
       Checks the owner PIN (lockout after 3 wrong tries) and returns a
       signed approval code. The code is tied to the exact action
       (payee/offer, amount, date), works once, and expires in 10 minutes.
  3. execute(action_id, code)         (Approvals page only)
       Re-checks the code against the action AS STORED NOW, so changing the
       amount after approval fails; re-runs the guard; then runs the action
       in the sandbox account / mock lender. Never touches real money.

Payment guard rules (per business, from core.owner_settings):
  - only verified, active payees on the owner's list
  - a payee name that merely looks like a verified one is refused
  - per-payment cap (the lower of the business cap and the payee's own cap)
  - daily cap across ALL of today's payments: executed ones plus ones still
    waiting or approved, so splitting one big payment into several small
    requests is caught
  - loans: the offer must belong to this business and be within the loan cap
"""
from __future__ import annotations

import difflib
import hashlib
import hmac
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from core.config import Config
from core.owner_settings import OwnerPin, PinError, load_settings
from db.audit import log_event

APPROVAL_VALID_FOR = timedelta(minutes=10)
REQUEST_VALID_FOR = timedelta(hours=24)
LOOKALIKE_RATIO = 0.8
TS = "%Y-%m-%dT%H:%M:%SZ"


class ApprovalError(Exception):
    pass


@dataclass
class GuardResult:
    allowed: bool
    reason: str


def _now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def _signing_key() -> bytes:
    from auth.session_manager import JWT_SECRET
    return hashlib.sha256(f"duka-approval|{JWT_SECRET}".encode()).digest()


def fingerprint(kind: str, payee_id: Optional[int], offer_id: Optional[int],
                amount_minor: int, scheduled_for: Optional[str]) -> str:
    """A code for the exact action: any change gives a different code."""
    body = {"kind": kind, "payee_id": payee_id, "offer_id": offer_id,
            "amount_minor": amount_minor, "scheduled_for": scheduled_for}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _norm(name: str) -> str:
    return " ".join(str(name or "").upper().split())


class ApprovalService:
    def __init__(self, db_path: Optional[str] = None, clock=_now):
        self.db_path = db_path or Config.DB_PATH
        self.clock = clock
        self.pins = OwnerPin(self.db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _audit(self, actor, event, business_id, action_id=None, decision=None, **details):
        log_event(self.db_path, actor, event, business_id=business_id, tier="T2",
                  decision=decision, entity_type="proposed_action", entity_id=action_id,
                  details=details)

    # ---- payee lookup (exact or refused) ----

    def resolve_payee(self, business_id: int, name: str) -> dict:
        """Find a verified payee by name. A near-miss ('S0KO SUPPLIES' for
        'SOKO SUPPLIES') is refused, not silently matched."""
        from core.owner_settings import list_payees
        payees = list_payees(self.db_path, business_id)
        wanted = _norm(name)
        for p in payees:
            if _norm(p["name"]) == wanted:
                return p
        close = [p for p in payees
                 if difflib.SequenceMatcher(None, _norm(p["name"]), wanted).ratio() >= LOOKALIKE_RATIO]
        if close:
            raise ApprovalError(
                f"'{name}' is not a verified payee. It looks like '{close[0]['name']}' but does not "
                f"match exactly, so it was refused (look-alike names are a common scam)."
            )
        raise ApprovalError(f"'{name}' is not on the owner's verified payee list.")

    # ---- the guard ----

    def committed_today(self, conn, business_id: int, exclude_action: Optional[int] = None) -> int:
        """Today's payments: AI requests that are executed, approved or waiting,
        plus standing-order payments authorized today. One daily cap covers both."""
        return committed_today_minor(conn, business_id, self.clock().strftime("%Y-%m-%d"),
                                     exclude_action=exclude_action)

    def check_payment(self, conn, business_id: int, payee_id: int, amount_minor: int,
                      exclude_action: Optional[int] = None) -> GuardResult:
        settings = load_settings(self.db_path, business_id)
        if not isinstance(amount_minor, int) or amount_minor <= 0:
            return GuardResult(False, "the amount must be more than zero")
        payee = conn.execute(
            "SELECT * FROM payee WHERE payee_id = ? AND business_id = ?", (payee_id, business_id)
        ).fetchone()
        if payee is None or not payee["active"]:
            return GuardResult(False, f"payee {payee_id} is not on the owner's payee list")
        if not payee["verified"]:
            return GuardResult(False, f"payee {payee['label_token']} has not been verified by the owner")
        cap = settings.per_txn_cap_minor
        if payee["per_txn_cap_minor"]:
            cap = min(cap, payee["per_txn_cap_minor"])
        if amount_minor > cap:
            return GuardResult(False, f"KES {amount_minor / 100:,.0f} is over the per-payment cap of "
                                      f"KES {cap / 100:,.0f}")
        so_far = self.committed_today(conn, business_id, exclude_action)
        if so_far + amount_minor > settings.daily_cap_minor:
            return GuardResult(False, f"this would bring today's payments to "
                                      f"KES {(so_far + amount_minor) / 100:,.0f}, over the daily cap of "
                                      f"KES {settings.daily_cap_minor / 100:,.0f}")
        return GuardResult(True, "allowed once the owner approves")

    def check_loan(self, conn, business_id: int, offer_id: int) -> tuple:
        offer = conn.execute(
            """SELECT fo.*, fr.business_id, cp.name AS product_name FROM financing_offer fo
               JOIN financing_request fr ON fr.request_id = fo.request_id
               JOIN credit_product cp ON cp.product_id = fo.product_id
               WHERE fo.offer_id = ?""",
            (offer_id,),
        ).fetchone()
        if offer is None or offer["business_id"] != business_id:
            return None, GuardResult(False, f"offer {offer_id} was not found for this business")
        cap = load_settings(self.db_path, business_id).loan_cap_minor
        if offer["principal_minor"] > cap:
            return offer, GuardResult(False, f"KES {offer['principal_minor'] / 100:,.0f} is over the loan cap "
                                             f"of KES {cap / 100:,.0f}")
        return offer, GuardResult(True, "allowed once the owner approves")

    # ---- step 1: propose (the AI's tools) ----

    def _save(self, conn, business_id, kind, payee_id, offer_id, amount_minor,
              scheduled_for, guard: GuardResult, created_by: str) -> dict:
        now = self.clock()
        fp = fingerprint(kind, payee_id, offer_id, amount_minor, scheduled_for)
        status = "PENDING_APPROVAL" if guard.allowed else "BLOCKED"
        action_id = conn.execute(
            """INSERT INTO proposed_action (business_id, kind, payee_id, offer_id, amount_minor,
                   currency_code, scheduled_for, payload_json, status, created_by, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, 'KES', ?, ?, ?, ?, ?, ?)""",
            (business_id, kind, payee_id, offer_id, amount_minor, scheduled_for,
             json.dumps({"fingerprint": fp, "guard": guard.reason}), status, created_by,
             now.strftime(TS), (now + REQUEST_VALID_FOR).strftime(TS)),
        ).lastrowid
        conn.commit()
        if guard.allowed:
            self._queue_notification(conn, business_id, action_id, kind, amount_minor, payee_id, offer_id)
        self._audit("agent" if created_by == "agent" else "owner", "ACTION_PROPOSED", business_id,
                    action_id, decision="pending" if guard.allowed else "blocked",
                    kind=kind, payee_id=payee_id, offer_id=offer_id,
                    amount_minor=amount_minor, reason=guard.reason)
        return {"action_id": action_id, "status": status, "reason": guard.reason}

    def propose_payment(self, business_id: int, amount_minor: int, payee_id: Optional[int] = None,
                        payee_name: Optional[str] = None, scheduled_for: Optional[str] = None,
                        created_by: str = "agent") -> dict:
        if payee_id is None:
            try:
                payee_id = self.resolve_payee(business_id, payee_name or "")["payee_id"]
            except ApprovalError as e:
                self._audit("guard", "ACTION_BLOCKED", business_id, decision="blocked",
                            kind="supplier_payment", payee_name=payee_name,
                            amount_minor=amount_minor, reason=str(e))
                return {"action_id": None, "status": "BLOCKED", "reason": str(e)}
        with self._conn() as conn:
            exists = conn.execute(
                "SELECT label_token FROM payee WHERE payee_id = ? AND business_id = ?",
                (payee_id, business_id),
            ).fetchone()
            guard = self.check_payment(conn, business_id, payee_id, amount_minor)
            if exists is None:
                # proposed_action.payee_id is a foreign key: an unknown payee
                # is refused and logged, never stored as a row.
                self._audit("guard", "ACTION_BLOCKED", business_id, decision="blocked",
                            kind="supplier_payment", payee_id=payee_id,
                            amount_minor=amount_minor, reason=guard.reason)
                return {"action_id": None, "status": "BLOCKED", "reason": guard.reason}
            result = self._save(conn, business_id, "supplier_payment", payee_id, None,
                                amount_minor, scheduled_for, guard, created_by)
            result.update({"payee": exists["label_token"], "amount_kes": amount_minor / 100})
        self._flush_pending_notice()
        return result

    def propose_loan(self, business_id: int, offer_id: int, created_by: str = "agent") -> dict:
        with self._conn() as conn:
            offer, guard = self.check_loan(conn, business_id, offer_id)
            if offer is None:
                self._audit("guard", "ACTION_BLOCKED", business_id, decision="blocked",
                            kind="loan_request", offer_id=offer_id, reason=guard.reason)
                return {"action_id": None, "status": "BLOCKED", "reason": guard.reason}
            result = self._save(conn, business_id, "loan_request", None, offer_id,
                                offer["principal_minor"], None, guard, created_by)
            result.update({
                "product": offer["product_name"],
                "principal_kes": offer["principal_minor"] / 100,
                "term_days": offer["term_days"],
                "total_repayment_kes": offer["total_repayment_minor"] / 100,
                "ear_pct": round((offer["ear"] or 0) * 100, 1),
            })
        self._flush_pending_notice()
        return result

    # ---- what the owner's Approvals page shows ----

    def list_actions(self, business_id: int, statuses: Optional[List[str]] = None,
                     limit: int = 50) -> List[dict]:
        sql = """SELECT pa.*, p.label_token AS payee_name, cp.name AS product_name, fo.term_days
                 FROM proposed_action pa
                 LEFT JOIN payee p ON p.payee_id = pa.payee_id
                 LEFT JOIN financing_offer fo ON fo.offer_id = pa.offer_id
                 LEFT JOIN credit_product cp ON cp.product_id = fo.product_id
                 WHERE pa.business_id = ?"""
        params: list = [business_id]
        if statuses:
            sql += f" AND pa.status IN ({','.join('?' * len(statuses))})"
            params += statuses
        sql += " ORDER BY pa.action_id DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            self._expire_old(conn, business_id)
            rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            payload = json.loads(r["payload_json"] or "{}")
            d["reason"] = payload.get("guard", "")
            d["receipt"] = payload.get("receipt")
            d["result"] = payload.get("result")
            out.append(d)
        return out

    def _expire_old(self, conn, business_id: int) -> None:
        """Requests nobody decided on in time expire. (An approved request
        whose code ran out is closed as BLOCKED at execute time: the schema's
        action_transition table allows APPROVED -> EXECUTED | BLOCKED only.)"""
        conn.execute(
            """UPDATE proposed_action SET status = 'EXPIRED'
               WHERE business_id = ? AND status = 'PENDING_APPROVAL' AND expires_at < ?""",
            (business_id, self.clock().strftime(TS)),
        )
        conn.commit()

    # ---- step 2: the owner decides (UI only) ----

    def _load(self, conn, action_id: int, business_id: int):
        row = conn.execute(
            "SELECT * FROM proposed_action WHERE action_id = ? AND business_id = ?",
            (action_id, business_id),
        ).fetchone()
        if row is None:
            raise ApprovalError("no such request for this business")
        return row

    def _sign(self, action_id: int, fp: str, expires_at: str) -> str:
        return hmac.new(_signing_key(), f"{action_id}|{fp}|{expires_at}".encode(), "sha256").hexdigest()

    def approve(self, action_id: int, business_id: int, pin: str,
                user_id: Optional[int] = None, ui_session_id: str = "ui") -> str:
        """Owner approves with their PIN. Returns the one-time approval code."""
        with self._conn() as conn:
            self._expire_old(conn, business_id)
            action = self._load(conn, action_id, business_id)
            if action["status"] != "PENDING_APPROVAL":
                raise ApprovalError(f"this request is {action['status'].lower().replace('_', ' ')}, "
                                    f"not waiting for approval")
            try:
                self.pins.verify(business_id, pin)
            except PinError as e:
                self._audit("owner", "APPROVAL_REFUSED", business_id, action_id,
                            decision="blocked", reason=str(e))
                raise ApprovalError(str(e)) from e
            fp = json.loads(action["payload_json"])["fingerprint"]
            expires = (self.clock() + APPROVAL_VALID_FOR).strftime(TS)
            code = self._sign(action_id, fp, expires)
            conn.execute(
                """INSERT INTO approval (action_id, decision, decided_by_user_id, ui_session_id, nonce)
                   VALUES (?, 'confirmed', ?, ?, ?)""",
                (action_id, user_id, ui_session_id, hashlib.sha256(code.encode()).hexdigest()),
            )
            conn.execute(
                "UPDATE proposed_action SET status = 'APPROVED', expires_at = ? WHERE action_id = ?",
                (expires, action_id),
            )
            conn.commit()
        self._audit("owner", "ACTION_APPROVED", business_id, action_id, decision="approved")
        return code

    def decline(self, action_id: int, business_id: int, user_id: Optional[int] = None,
                ui_session_id: str = "ui") -> None:
        """Turning a request down needs no PIN (it can't move money)."""
        with self._conn() as conn:
            action = self._load(conn, action_id, business_id)
            if action["status"] != "PENDING_APPROVAL":
                raise ApprovalError("this request is not waiting for approval")
            conn.execute(
                """INSERT INTO approval (action_id, decision, decided_by_user_id, ui_session_id, nonce)
                   VALUES (?, 'rejected', ?, ?, ?)""",
                (action_id, user_id, ui_session_id, secrets.token_hex(16)),
            )
            conn.execute("UPDATE proposed_action SET status = 'REJECTED' WHERE action_id = ?", (action_id,))
            conn.commit()
        self._audit("owner", "ACTION_DECLINED", business_id, action_id, decision="rejected")

    # ---- step 3: carry it out in the sandbox (UI only) ----

    def execute(self, action_id: int, business_id: int, code: Optional[str],
                actor: str = "owner") -> dict:
        """Run an approved action. The code must match the action as it is
        stored right now, must not have been used, and must not be expired."""
        with self._conn() as conn:
            try:
                action = self._load(conn, action_id, business_id)
                approval = conn.execute(
                    "SELECT * FROM approval WHERE action_id = ? AND decision = 'confirmed'", (action_id,)
                ).fetchone()
                if approval is None or action["status"] not in ("APPROVED", "EXECUTED"):
                    raise ApprovalError("the owner has not approved this request")
                if approval["nonce_used_at"] or action["status"] == "EXECUTED":
                    raise ApprovalError("this approval has already been used")
                fp_now = fingerprint(action["kind"], action["payee_id"], action["offer_id"],
                                     action["amount_minor"], action["scheduled_for"])
                expected = self._sign(action_id, fp_now, action["expires_at"])
                if (not isinstance(code, str)
                        or not hmac.compare_digest(code, expected)
                        or hashlib.sha256(code.encode()).hexdigest() != approval["nonce"]):
                    raise ApprovalError("the approval code is not valid for this exact request")
                if self.clock().strftime(TS) > action["expires_at"]:
                    self._close_unrun(conn, action, approval, "the approval expired")
                    raise ApprovalError("the approval has expired")
            except ApprovalError as e:
                self._audit(actor, "EXECUTE_BLOCKED", business_id, action_id,
                            decision="blocked", reason=str(e))
                return {"status": "blocked", "reason": str(e)}

            # Rules are checked again: caps may have changed since approval.
            if action["kind"] == "supplier_payment":
                guard = self.check_payment(conn, business_id, action["payee_id"],
                                           action["amount_minor"], exclude_action=action_id)
            else:
                _, guard = self.check_loan(conn, business_id, action["offer_id"])
            if not guard.allowed:
                self._close_unrun(conn, action, approval, guard.reason)
                self._audit(actor, "EXECUTE_BLOCKED", business_id, action_id,
                            decision="blocked", reason=guard.reason)
                return {"status": "blocked", "reason": guard.reason}

            account_id, balance = self._sandbox_account(conn, business_id)
            receipt = f"SBX-{business_id}-{action_id}-{secrets.token_hex(3).upper()}"
            if action["kind"] == "supplier_payment":
                if action["amount_minor"] > balance:
                    reason = (f"not enough money in the sandbox account: balance KES "
                              f"{balance / 100:,.0f} (the sandbox has no overdraft)")
                    self._close_unrun(conn, action, approval, reason)
                    self._audit(actor, "EXECUTE_FAILED", business_id, action_id,
                                decision="failed", reason=reason)
                    return {"status": "failed", "reason": reason}
                balance -= action["amount_minor"]
                sbx_kind, result = "payment", {"paid_kes": action["amount_minor"] / 100}
            else:
                offer = conn.execute("SELECT * FROM financing_offer WHERE offer_id = ?",
                                     (action["offer_id"],)).fetchone()
                balance += offer["net_received_minor"]
                conn.execute(
                    """INSERT INTO mock_lender_decision (action_id, decision, reference, reason)
                       VALUES (?, 'approved', ?, 'sandbox lender')""",
                    (action_id, receipt),
                )
                sbx_kind, result = "loan_disbursement", {
                    "received_kes": offer["net_received_minor"] / 100,
                    "total_to_repay_kes": offer["total_repayment_minor"] / 100,
                }
            conn.execute(
                """INSERT INTO sandbox_txn (action_id, business_id, sandbox_account_id, kind, payee_id,
                       amount_minor, receipt_ref, result, balance_after_minor)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'success', ?)""",
                (action_id, business_id, account_id, sbx_kind, action["payee_id"],
                 action["amount_minor"], receipt, balance),
            )
            conn.execute("UPDATE sandbox_account SET balance_minor = ? WHERE sandbox_account_id = ?",
                         (balance, account_id))
            payload = json.loads(action["payload_json"])
            payload.update({"receipt": receipt, "result": result})
            conn.execute("UPDATE proposed_action SET status = 'EXECUTED', payload_json = ? WHERE action_id = ?",
                         (json.dumps(payload), action_id))
            conn.execute("UPDATE approval SET nonce_used_at = ? WHERE approval_id = ?",
                         (self.clock().strftime(TS), approval["approval_id"]))
            conn.commit()
        self._audit(actor, "ACTION_EXECUTED", business_id, action_id, decision="executed",
                    receipt=receipt, balance_after_minor=balance, **result)
        self._notify(business_id, action_id, "Approved request carried out",
                     f"Duka: request #{action_id} was carried out in the sandbox. Receipt {receipt}.")
        return {"status": "done", "receipt": receipt, "balance_kes": balance / 100, **result}

    def _close_unrun(self, conn, action, approval, reason: str) -> None:
        """An approved request that could not run is closed (BLOCKED, with the
        reason) and its code is spent, so it can't be replayed later."""
        payload = json.loads(action["payload_json"])
        payload["guard"] = f"approved, but not carried out: {reason}"
        conn.execute("UPDATE proposed_action SET status = 'BLOCKED', payload_json = ? WHERE action_id = ?",
                     (json.dumps(payload), action["action_id"]))
        conn.execute("UPDATE approval SET nonce_used_at = ? WHERE approval_id = ?",
                     (self.clock().strftime(TS), approval["approval_id"]))
        conn.commit()

    def approve_and_execute(self, action_id: int, business_id: int, pin: str,
                            user_id: Optional[int] = None, ui_session_id: str = "ui") -> dict:
        """What the owner's Approve button does: PIN -> code -> run."""
        try:
            code = self.approve(action_id, business_id, pin, user_id, ui_session_id)
        except ApprovalError as e:
            return {"status": "blocked", "reason": str(e)}
        return self.execute(action_id, business_id, code)

    # ---- notifications (shared with standing orders) ----

    def _queue_notification(self, conn, business_id, action_id, kind, amount_minor, payee_id, offer_id):
        if kind == "supplier_payment":
            who = conn.execute("SELECT label_token FROM payee WHERE payee_id = ?", (payee_id,)).fetchone()
            what = f"pay {who[0] if who else 'a payee'} KES {amount_minor / 100:,.0f}"
        else:
            what = f"take a loan of KES {amount_minor / 100:,.0f} (offer #{offer_id})"
        self._pending_notice = (business_id, action_id, "Approval needed",
                                f"Duka: your assistant asks to {what}. Nothing happens until you "
                                f"approve it with your Duka PIN on the Approvals page. Duka never asks "
                                f"for your PIN by SMS or call.")

    def _flush_pending_notice(self):
        notice = getattr(self, "_pending_notice", None)
        self._pending_notice = None
        if notice:
            self._notify(*notice)

    def _notify(self, business_id: int, action_id: int, title: str, body: str) -> None:
        """In-app notification for every owner/manager, plus an SMS where they
        turned SMS on, via the same pipeline as standing-order reminders.
        Best-effort: a failed SMS never undoes the request."""
        try:
            from core.standing_orders import StandingOrderService
            so = StandingOrderService(self.db_path)
            outbox = []
            with self._conn() as conn:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(notification)")}
                if "action_id" not in cols:
                    return
                for user_id in so._approvers(conn, business_id):
                    conn.execute(
                        """INSERT INTO notification (business_id, user_id, action_id, channel, title, body, status)
                           VALUES (?, ?, ?, 'in_app', ?, ?, 'sent')""",
                        (business_id, user_id, action_id, title, body),
                    )
                    contact = conn.execute(
                        "SELECT sms_enabled FROM notification_contact WHERE business_id = ? AND user_id = ?",
                        (business_id, user_id),
                    ).fetchone()
                    phone = so._contact_phone(business_id, user_id, conn)
                    if contact and contact["sms_enabled"] and phone:
                        outbox.append((user_id, phone))
            for user_id, phone in outbox:
                result = so.sms_sender(phone, body)
                with self._conn() as conn:
                    conn.execute(
                        """INSERT INTO notification (business_id, user_id, action_id, channel, title, body,
                               status, provider_ref, error)
                           VALUES (?, ?, ?, 'sms', ?, ?, ?, ?, ?)""",
                        (business_id, user_id, action_id, title, body,
                         "sent" if result.ok else "failed", result.provider_ref, result.error),
                    )
        except Exception:
            pass

    def unread_count(self, business_id: int, user_id: int) -> int:
        with self._conn() as conn:
            return conn.execute(
                """SELECT COUNT(*) FROM notification WHERE business_id = ? AND user_id = ?
                   AND channel = 'in_app' AND status = 'sent' AND action_id IS NOT NULL""",
                (business_id, user_id),
            ).fetchone()[0]

    def mark_read(self, business_id: int, user_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE notification SET status = 'read', read_at = ?
                   WHERE business_id = ? AND user_id = ? AND channel = 'in_app' AND status = 'sent'
                     AND action_id IS NOT NULL""",
                (self.clock().strftime(TS), business_id, user_id),
            )

    def _sandbox_account(self, conn, business_id: int):
        """The business's pretend account; opens with its latest statement balance."""
        row = conn.execute(
            "SELECT sandbox_account_id, balance_minor FROM sandbox_account WHERE business_id = ?",
            (business_id,),
        ).fetchone()
        if row:
            return row[0], row[1]
        opening = conn.execute(
            """SELECT balance_after_minor FROM transaction_ledger
               WHERE business_id = ? AND voided = 0 AND balance_after_minor IS NOT NULL
               ORDER BY local_date DESC, ts DESC, txn_id DESC LIMIT 1""",
            (business_id,),
        ).fetchone()
        balance = opening[0] if opening else 0
        account_id = conn.execute(
            "INSERT INTO sandbox_account (business_id, balance_minor) VALUES (?, ?)", (business_id, balance)
        ).lastrowid
        return account_id, balance


def committed_today_minor(conn, business_id: int, day: str, exclude_action: Optional[int] = None,
                          exclude_payment: Optional[int] = None) -> int:
    """Everything paid or on its way out on `day`, across both payment paths:
    AI requests (waiting, approved or executed) and standing-order payments
    the owner authorized. Both paths check their daily cap against this."""
    ai = conn.execute(
        """SELECT COALESCE(SUM(amount_minor), 0) FROM proposed_action
           WHERE business_id = ? AND kind = 'supplier_payment'
             AND status IN ('PENDING_APPROVAL', 'APPROVED', 'EXECUTED')
             AND substr(created_at, 1, 10) = ? AND action_id IS NOT ?""",
        (business_id, day, exclude_action),
    ).fetchone()[0]
    try:
        standing = conn.execute(
            """SELECT COALESCE(SUM(amount_minor), 0) FROM scheduled_payment
               WHERE business_id = ? AND status IN ('authorized', 'stk_sent', 'paid')
                 AND substr(authorized_at, 1, 10) = ? AND payment_id IS NOT ?""",
            (business_id, day, exclude_payment),
        ).fetchone()[0]
    except sqlite3.OperationalError:     # standing orders not installed
        standing = 0
    return ai + standing
