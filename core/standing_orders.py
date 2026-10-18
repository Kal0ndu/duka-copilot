"""Standing orders: scheduled payments the owner authorizes one by one.

Flow (the AI never pays):
  1. The owner creates a standing order (like M-Pesa Ratiba).
  2. run() creates a scheduled_payment for each upcoming due date, ranks it
     with core.payment_priority, and notifies the owner in-app and by SMS.
  3. The owner taps Authorize in the UI -> authorize_and_push() sends an
     M-Pesa STK prompt to the owner's own verified phone.
  4. Money moves only after the owner enters their M-Pesa PIN on that
     prompt; check_status() confirms it with Daraja.

authorize_and_push() is registered in agent/tools.py as UI-only
(exposed_to_llm=False), and the orchestrator refuses to dispatch it.

Run the scheduler from cron for SMS reminders even when nobody opens the app:
    python -m core.standing_orders
"""
from __future__ import annotations

import calendar
import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional

from auth.phone_utils import hash_phone, mask_phone, normalise_phone
from core.config import Config
from core.payment_priority import PaymentCandidate, rank_payments
from db.audit import log_event
from integrations.mpesa_daraja import DarajaClient, DarajaError
from integrations.sms import SmsResult, send_sms

KINDS = ["rent", "loan_repayment", "utility", "wages", "tax", "school_fees",
         "insurance", "supplier_standing", "savings", "other"]
CADENCES = ["weekly", "biweekly", "monthly", "quarterly", "one_off"]
OPEN_STATUSES = ("pending", "notified", "authorized", "stk_sent", "failed")
AUTHORIZABLE = ("pending", "notified", "failed")
APPROVER_ROLES = ("owner", "manager")


class PaymentNotAllowed(Exception):
    """The owner action was refused (wrong state, role, cap, or missing phone)."""


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_months(d: date, months: int, anchor_day: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def next_occurrence(current: date, cadence: str, anchor_day: int) -> Optional[date]:
    if cadence == "weekly":
        return current + timedelta(days=7)
    if cadence == "biweekly":
        return current + timedelta(days=14)
    if cadence == "monthly":
        return _add_months(current, 1, anchor_day)
    if cadence == "quarterly":
        return _add_months(current, 3, anchor_day)
    return None  # one_off


def first_due_on_or_after(start: date, cadence: str, today: date) -> date:
    """First due date >= today, so a past start date doesn't backfill old payments."""
    due = start
    while due < today:
        nxt = next_occurrence(due, cadence, start.day)
        if nxt is None:
            return due  # one-off in the past: due now (shows as overdue)
        due = nxt
    return due


class StandingOrderService:
    def __init__(
        self,
        db_path: Optional[str] = None,
        daraja: Optional[DarajaClient] = None,
        sms_sender: Callable[[str, str], SmsResult] = send_sms,
        today_fn: Callable[[], date] = date.today,
    ):
        self.db_path = db_path or Config.DB_PATH
        self._daraja = daraja
        self.sms_sender = sms_sender
        self.today_fn = today_fn

    @property
    def daraja(self) -> DarajaClient:
        if self._daraja is None:
            self._daraja = DarajaClient.from_env()
        return self._daraja

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _audit(self, event_type: str, business_id: int, **kwargs) -> None:
        log_event(self.db_path, actor=kwargs.pop("actor", "system"), event_type=event_type,
                  business_id=business_id, **kwargs)

    # ---- standing orders ----

    @staticmethod
    def _validate_destination(destination_type: str, number: str, account_reference: Optional[str]) -> str:
        number = (number or "").strip()
        if destination_type == "phone":
            return normalise_phone(number)
        if destination_type not in ("paybill", "till"):
            raise ValueError(f"Unknown destination type: {destination_type}")
        if not re.fullmatch(r"\d{5,7}", number):
            raise ValueError(f"{destination_type.title()} number must be 5–7 digits.")
        if destination_type == "paybill" and not (account_reference or "").strip():
            raise ValueError("Paybill payments need an account number.")
        return number

    def create_order(
        self,
        business_id: int,
        user_id: Optional[int],
        label: str,
        kind: str,
        destination_type: str,
        destination_number: str,
        amount_kes: int,
        cadence: str,
        start_date: date,
        end_date: Optional[date] = None,
        account_reference: Optional[str] = None,
        essential: bool = True,
        late_penalty_kes: int = 0,
        remind_days_before: int = 2,
    ) -> int:
        if kind not in KINDS:
            raise ValueError(f"Unknown kind: {kind}")
        if cadence not in CADENCES:
            raise ValueError(f"Unknown cadence: {cadence}")
        if not label.strip():
            raise ValueError("Give the standing order a name.")
        amount_minor = int(amount_kes) * 100
        if amount_minor <= 0:
            raise ValueError("Amount must be at least KES 1.")
        if amount_minor > Config.CAP_PER_TXN:
            raise ValueError(f"Amount exceeds the per-payment limit of KES {Config.CAP_PER_TXN / 100:,.0f}.")
        if end_date and end_date < start_date:
            raise ValueError("End date is before the start date.")
        number = self._validate_destination(destination_type, destination_number, account_reference)
        next_due = first_due_on_or_after(start_date, cadence, self.today_fn())

        with self._conn() as conn:
            so_id = conn.execute(
                """INSERT INTO standing_order (business_id, created_by_user_id, label, kind,
                       destination_type, destination_number, account_reference, amount_minor,
                       cadence, start_date, next_due, end_date, essential, late_penalty_minor,
                       remind_days_before)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (business_id, user_id, label.strip()[:80], kind, destination_type, number,
                 (account_reference or "").strip()[:30] or None, amount_minor, cadence,
                 start_date.isoformat(), next_due.isoformat(),
                 end_date.isoformat() if end_date else None, 1 if essential else 0,
                 int(late_penalty_kes) * 100, int(remind_days_before)),
            ).lastrowid
        self._audit("STANDING_ORDER_CREATED", business_id, actor="owner",
                    entity_type="standing_order", entity_id=so_id,
                    details={"kind": kind, "cadence": cadence, "amount_minor": amount_minor})
        return so_id

    def list_orders(self, business_id: int) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM standing_order WHERE business_id = ? AND status != 'ended'
                   ORDER BY status, next_due""",
                (business_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def set_order_status(self, business_id: int, standing_order_id: int, status: str) -> None:
        if status not in ("active", "paused", "ended"):
            raise ValueError(status)
        with self._conn() as conn:
            conn.execute(
                "UPDATE standing_order SET status = ? WHERE standing_order_id = ? AND business_id = ?",
                (status, standing_order_id, business_id),
            )
            if status != "active":
                # Unpaid reminders for a paused/ended order no longer apply.
                conn.execute(
                    """UPDATE scheduled_payment SET status = 'skipped'
                       WHERE standing_order_id = ? AND business_id = ? AND status IN ('pending','notified')""",
                    (standing_order_id, business_id),
                )
        self._audit("STANDING_ORDER_STATUS", business_id, actor="owner",
                    entity_type="standing_order", entity_id=standing_order_id, details={"status": status})

    # ---- notification contact ----

    def set_contact(self, business_id: int, user_id: int, phone_raw: str, sms_enabled: bool = True) -> str:
        """Save the phone for SMS and STK prompts. It must be the account's login phone."""
        phone = normalise_phone(phone_raw)
        phone_hash = hash_phone(phone)
        with self._conn() as conn:
            row = conn.execute("SELECT phone_hash FROM app_user WHERE user_id = ?", (user_id,)).fetchone()
            if not row or row["phone_hash"] != phone_hash:
                raise PaymentNotAllowed(
                    "Use the phone number you log in with. Payment prompts can only go to your own phone."
                )
            token = f"PHONE_U{user_id}_B{business_id}"
            conn.execute(
                """INSERT INTO token_vault (token, business_id, entity_type, original_value)
                   VALUES (?, ?, 'PHONE', ?)
                   ON CONFLICT (business_id, token) DO UPDATE SET original_value = excluded.original_value""",
                (token, business_id, phone),
            )
            conn.execute(
                """INSERT INTO notification_contact (business_id, user_id, phone_token, phone_hash, sms_enabled, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (business_id, user_id) DO UPDATE SET
                     phone_token = excluded.phone_token, phone_hash = excluded.phone_hash,
                     sms_enabled = excluded.sms_enabled, updated_at = excluded.updated_at""",
                (business_id, user_id, token, phone_hash, 1 if sms_enabled else 0, _now()),
            )
        return mask_phone(phone)

    def get_contact(self, business_id: int, user_id: int) -> Optional[Dict]:
        phone = self._contact_phone(business_id, user_id)
        if not phone:
            return None
        with self._conn() as conn:
            row = conn.execute(
                "SELECT sms_enabled FROM notification_contact WHERE business_id = ? AND user_id = ?",
                (business_id, user_id),
            ).fetchone()
        return {"phone_masked": mask_phone(phone), "sms_enabled": bool(row["sms_enabled"])}

    def _contact_phone(self, business_id: int, user_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[str]:
        own = conn is None
        conn = conn or self._conn()
        try:
            row = conn.execute(
                """SELECT v.original_value, c.phone_hash, u.phone_hash AS login_hash
                   FROM notification_contact c
                   JOIN token_vault v ON v.business_id = c.business_id AND v.token = c.phone_token
                   JOIN app_user u ON u.user_id = c.user_id
                   WHERE c.business_id = ? AND c.user_id = ?""",
                (business_id, user_id),
            ).fetchone()
        finally:
            if own:
                conn.close()
        # Re-check on every use: if the login phone changed, the old number is not trusted.
        if not row or row["phone_hash"] != row["login_hash"] or hash_phone(row["original_value"]) != row["login_hash"]:
            return None
        return row["original_value"]

    def _approvers(self, conn: sqlite3.Connection, business_id: int) -> List[int]:
        rows = conn.execute(
            f"""SELECT user_id FROM business_member WHERE business_id = ?
                  AND role IN ({",".join("?" * len(APPROVER_ROLES))})
                UNION
                SELECT owner_user_id FROM business WHERE business_id = ? AND owner_user_id IS NOT NULL""",
            (business_id, *APPROVER_ROLES, business_id),
        ).fetchall()
        return [r[0] for r in rows]

    # ---- scheduler ----

    def generate_due(self, business_id: Optional[int] = None) -> int:
        """Create scheduled payments whose reminder window has opened."""
        today = self.today_fn()
        created = 0
        with self._conn() as conn:
            sql = "SELECT * FROM standing_order WHERE status = 'active' AND next_due IS NOT NULL"
            params: tuple = ()
            if business_id is not None:
                sql += " AND business_id = ?"
                params = (business_id,)
            for so in conn.execute(sql, params).fetchall():
                due = date.fromisoformat(so["next_due"])
                end = date.fromisoformat(so["end_date"]) if so["end_date"] else None
                anchor = date.fromisoformat(so["start_date"]).day
                while due is not None and due - timedelta(days=so["remind_days_before"]) <= today:
                    if end and due > end:
                        due = None
                        break
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO scheduled_payment
                               (standing_order_id, business_id, due_date, amount_minor)
                           VALUES (?, ?, ?, ?)""",
                        (so["standing_order_id"], so["business_id"], due.isoformat(), so["amount_minor"]),
                    )
                    created += cur.rowcount
                    due = next_occurrence(due, so["cadence"], anchor)
                if due is None or (end and due > end):
                    conn.execute(
                        "UPDATE standing_order SET next_due = NULL, status = 'ended' WHERE standing_order_id = ?",
                        (so["standing_order_id"],),
                    )
                else:
                    conn.execute(
                        "UPDATE standing_order SET next_due = ? WHERE standing_order_id = ?",
                        (due.isoformat(), so["standing_order_id"]),
                    )
        return created

    def _balance_minor(self, conn: sqlite3.Connection, business_id: int) -> Optional[int]:
        row = conn.execute(
            """SELECT balance_after_minor FROM transaction_ledger
               WHERE business_id = ? AND voided = 0 AND balance_after_minor IS NOT NULL
               ORDER BY local_date DESC, ts DESC, txn_id DESC LIMIT 1""",
            (business_id,),
        ).fetchone()
        return row[0] if row else None

    def reprioritise(self, business_id: int) -> None:
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT p.payment_id, p.amount_minor, p.due_date, s.label, s.kind, s.essential,
                           s.late_penalty_minor
                    FROM scheduled_payment p JOIN standing_order s USING (standing_order_id)
                    WHERE p.business_id = ? AND p.status IN ({",".join("?" * len(AUTHORIZABLE))})""",
                (business_id, *AUTHORIZABLE),
            ).fetchall()
            candidates = [
                PaymentCandidate(r["payment_id"], r["label"], r["kind"], r["amount_minor"],
                                 date.fromisoformat(r["due_date"]), bool(r["essential"]),
                                 r["late_penalty_minor"])
                for r in rows
            ]
            ranked = rank_payments(candidates, self.today_fn(), self._balance_minor(conn, business_id),
                                   Config.SAFETY_BUFFER_MINOR)
            for p in ranked:
                conn.execute(
                    """UPDATE scheduled_payment SET priority_score = ?, priority_band = ?,
                           priority_reasons_json = ? WHERE payment_id = ?""",
                    (p.score, p.band, json.dumps(p.reasons), p.payment_id),
                )

    def _sms_body(self, payment: sqlite3.Row) -> str:
        due = date.fromisoformat(payment["due_date"])
        base = os.getenv("APP_BASE_URL", "").rstrip("/")
        link = f" Open: {base}/Standing_Orders?pay={payment['payment_id']}" if base else " Open the Duka app to authorize."
        return (
            f"Duka: KES {payment['amount_minor'] / 100:,.0f} for {payment['label']} is due "
            f"{due.strftime('%a %d %b')} (priority {payment['priority_band'].upper()}).{link} "
            "Duka never asks for your M-Pesa PIN by SMS or call."
        )

    def dispatch_notifications(self, business_id: Optional[int] = None) -> int:
        """Notify approvers about payments that haven't been announced yet."""
        outbox = []  # SMS go out after commit so a slow provider never holds the DB lock
        with self._conn() as conn:
            sql = """SELECT p.*, s.label FROM scheduled_payment p JOIN standing_order s USING (standing_order_id)
                     WHERE p.status = 'pending'"""
            params: tuple = ()
            if business_id is not None:
                sql += " AND p.business_id = ?"
                params = (business_id,)
            payments = conn.execute(sql, params).fetchall()
            for p in payments:
                title = f"{p['priority_band'].title()} priority: {p['label']}"
                body = self._sms_body(p)
                for user_id in self._approvers(conn, p["business_id"]):
                    conn.execute(
                        """INSERT INTO notification (business_id, user_id, payment_id, channel, title, body, status)
                           VALUES (?, ?, ?, 'in_app', ?, ?, 'sent')""",
                        (p["business_id"], user_id, p["payment_id"], title, body),
                    )
                    contact = conn.execute(
                        "SELECT sms_enabled FROM notification_contact WHERE business_id = ? AND user_id = ?",
                        (p["business_id"], user_id),
                    ).fetchone()
                    phone = self._contact_phone(p["business_id"], user_id, conn)
                    if contact and contact["sms_enabled"] and phone:
                        outbox.append((p["business_id"], user_id, p["payment_id"], phone, title, body))
                conn.execute(
                    "UPDATE scheduled_payment SET status = 'notified', notified_at = ? WHERE payment_id = ?",
                    (_now(), p["payment_id"]),
                )

        for bid, user_id, payment_id, phone, title, body in outbox:
            result = self.sms_sender(phone, body)
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO notification (business_id, user_id, payment_id, channel, title, body,
                           status, provider_ref, error)
                       VALUES (?, ?, ?, 'sms', ?, ?, ?, ?, ?)""",
                    (bid, user_id, payment_id, title, body,
                     "sent" if result.ok else "failed", result.provider_ref, result.error),
                )
        return len(payments)

    def run(self, business_id: Optional[int] = None) -> Dict[str, int]:
        """Scheduler tick: generate due payments, rank them, notify. Idempotent."""
        created = self.generate_due(business_id)
        if business_id is not None:
            business_ids = [business_id]
        else:
            with self._conn() as conn:
                business_ids = [r[0] for r in conn.execute(
                    "SELECT DISTINCT business_id FROM scheduled_payment WHERE status IN ('pending','notified','failed')"
                )]
        for bid in business_ids:
            self.reprioritise(bid)
        notified = self.dispatch_notifications(business_id)
        return {"created": created, "notified": notified}

    # ---- queries ----

    def open_payments(self, business_id: int) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT p.*, s.label, s.kind, s.destination_type, s.destination_number,
                           s.account_reference, s.essential
                    FROM scheduled_payment p JOIN standing_order s USING (standing_order_id)
                    WHERE p.business_id = ? AND p.status IN ({",".join("?" * len(OPEN_STATUSES))})
                    ORDER BY p.priority_score DESC, p.due_date""",
                (business_id, *OPEN_STATUSES),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["priority_reasons"] = json.loads(d.pop("priority_reasons_json") or "[]")
            out.append(d)
        return out

    def history(self, business_id: int, limit: int = 50) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT p.payment_id, p.due_date, p.amount_minor, p.status, p.paid_at, p.mpesa_receipt,
                          s.label
                   FROM scheduled_payment p JOIN standing_order s USING (standing_order_id)
                   WHERE p.business_id = ? AND p.status IN ('paid','skipped')
                   ORDER BY COALESCE(p.paid_at, p.due_date) DESC LIMIT ?""",
                (business_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def unread_count(self, business_id: int, user_id: int) -> int:
        with self._conn() as conn:
            return conn.execute(
                """SELECT COUNT(*) FROM notification
                   WHERE business_id = ? AND user_id = ? AND channel = 'in_app' AND status = 'sent'""",
                (business_id, user_id),
            ).fetchone()[0]

    def mark_read(self, business_id: int, user_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE notification SET status = 'read', read_at = ?
                   WHERE business_id = ? AND user_id = ? AND channel = 'in_app' AND status = 'sent'""",
                (_now(), business_id, user_id),
            )

    def priorities_for_agent(self, business_id: int) -> List[Dict]:
        """Read-only, PII-free view for the LLM: no destination numbers or phones."""
        return [
            {
                "label": p["label"],
                "kind": p["kind"],
                "amount_kes": p["amount_minor"] / 100,
                "due_date": p["due_date"],
                "status": p["status"],
                "priority_score": p["priority_score"],
                "priority_band": p["priority_band"],
                "reasons": p["priority_reasons"],
            }
            for p in self.open_payments(business_id)
        ]

    # ---- owner actions (UI only; never exposed to the agent) ----

    def _require_approver(self, conn: sqlite3.Connection, business_id: int, user_id: int) -> None:
        if user_id not in self._approvers(conn, business_id):
            raise PaymentNotAllowed("Only the business owner or a manager can authorize payments.")

    def authorize_and_push(self, payment_id: int, business_id: int, user_id: int) -> Dict:
        """Owner tapped Authorize: send an STK prompt to their own phone."""
        conn = self._conn()
        try:
            self._require_approver(conn, business_id, user_id)
            phone = self._contact_phone(business_id, user_id, conn)
            if not phone:
                raise PaymentNotAllowed("Add your M-Pesa phone number in Notification settings first.")

            payment = conn.execute(
                """SELECT p.*, s.label, s.destination_type, s.destination_number, s.account_reference
                   FROM scheduled_payment p JOIN standing_order s USING (standing_order_id)
                   WHERE p.payment_id = ? AND p.business_id = ?""",
                (payment_id, business_id),
            ).fetchone()
            if payment is None:
                raise PaymentNotAllowed("Payment not found.")
            if payment["amount_minor"] > Config.CAP_PER_TXN:
                raise PaymentNotAllowed("Amount exceeds the per-payment limit.")
            spent_today = conn.execute(
                """SELECT COALESCE(SUM(amount_minor), 0) FROM scheduled_payment
                   WHERE business_id = ? AND status IN ('authorized','stk_sent','paid')
                     AND substr(authorized_at, 1, 10) = ?""",
                (business_id, datetime.utcnow().strftime("%Y-%m-%d")),
            ).fetchone()[0]
            if spent_today + payment["amount_minor"] > Config.CAP_DAILY:
                raise PaymentNotAllowed("This would exceed today's payment limit.")

            # Compare-and-set: a double tap or a second tab cannot push twice.
            previous = payment["status"]
            claimed = conn.execute(
                f"""UPDATE scheduled_payment SET status = 'authorized', authorized_by_user_id = ?, authorized_at = ?
                    WHERE payment_id = ? AND business_id = ? AND status IN ({",".join("?" * len(AUTHORIZABLE))})""",
                (user_id, _now(), payment_id, business_id, *AUTHORIZABLE),
            ).rowcount
            conn.commit()
            if not claimed:
                raise PaymentNotAllowed(f"This payment is already {previous.replace('_', ' ')}.")

            reference = payment["account_reference"] or payment["destination_number"]
            try:
                push = self.daraja.stk_push(phone, payment["amount_minor"] // 100, reference, payment["label"])
            except DarajaError as e:
                conn.execute("UPDATE scheduled_payment SET status = 'failed' WHERE payment_id = ?", (payment_id,))
                conn.commit()
                self._audit("STK_PUSH_FAILED", business_id, actor="owner", entity_type="scheduled_payment",
                            entity_id=payment_id, decision="error", details={"error": str(e)})
                raise PaymentNotAllowed(str(e)) from e

            conn.execute(
                """INSERT INTO mpesa_stk_request (payment_id, business_id, environment, merchant_request_id,
                       checkout_request_id, phone_hash, amount_minor)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (payment_id, business_id, self.daraja.env, push.merchant_request_id,
                 push.checkout_request_id, hash_phone(phone), payment["amount_minor"]),
            )
            conn.execute("UPDATE scheduled_payment SET status = 'stk_sent' WHERE payment_id = ?", (payment_id,))
            conn.commit()
        finally:
            conn.close()

        self._audit("PAYMENT_AUTHORIZED", business_id, actor="owner", entity_type="scheduled_payment",
                    entity_id=payment_id, decision="stk_sent",
                    details={"user_id": user_id, "env": self.daraja.env, "amount_minor": payment["amount_minor"]})
        return {"status": "stk_sent", "phone_masked": mask_phone(phone), "message": push.customer_message}

    def check_status(self, payment_id: int, business_id: int) -> Dict:
        """Ask Daraja whether the owner completed the STK prompt."""
        with self._conn() as conn:
            stk = conn.execute(
                """SELECT * FROM mpesa_stk_request WHERE payment_id = ? AND business_id = ?
                   ORDER BY stk_id DESC LIMIT 1""",
                (payment_id, business_id),
            ).fetchone()
        if stk is None:
            raise PaymentNotAllowed("No M-Pesa prompt has been sent for this payment.")
        if stk["status"] != "sent":
            return {"state": stk["status"], "result_desc": stk["result_desc"]}

        try:
            result = self.daraja.stk_query(stk["checkout_request_id"])
        except DarajaError as e:
            return {"state": "pending", "result_desc": str(e)}
        if result.state == "pending":
            return {"state": "pending", "result_desc": result.result_desc}

        with self._conn() as conn:
            conn.execute(
                """UPDATE mpesa_stk_request SET status = ?, result_code = ?, result_desc = ?, mpesa_receipt = ?,
                       updated_at = ? WHERE stk_id = ?""",
                (result.state, result.result_code, result.result_desc, result.mpesa_receipt, _now(), stk["stk_id"]),
            )
            if result.state == "success":
                conn.execute(
                    "UPDATE scheduled_payment SET status = 'paid', paid_at = ?, mpesa_receipt = ? WHERE payment_id = ?",
                    (_now(), result.mpesa_receipt, payment_id),
                )
            else:
                conn.execute("UPDATE scheduled_payment SET status = 'failed' WHERE payment_id = ?", (payment_id,))
        self._audit("PAYMENT_RESULT", business_id, entity_type="scheduled_payment", entity_id=payment_id,
                    decision=result.state, details={"result_code": result.result_code})
        return {"state": result.state, "result_desc": result.result_desc}

    def skip(self, payment_id: int, business_id: int, user_id: int) -> None:
        with self._conn() as conn:
            self._require_approver(conn, business_id, user_id)
            changed = conn.execute(
                """UPDATE scheduled_payment SET status = 'skipped'
                   WHERE payment_id = ? AND business_id = ? AND status IN ('pending','notified','failed')""",
                (payment_id, business_id),
            ).rowcount
        if not changed:
            raise PaymentNotAllowed("This payment can no longer be skipped.")
        self._audit("PAYMENT_SKIPPED", business_id, actor="owner", entity_type="scheduled_payment",
                    entity_id=payment_id, details={"user_id": user_id})


def main() -> None:
    result = StandingOrderService().run()
    print(f"Standing orders: {result['created']} payment(s) created, {result['notified']} notified.")


if __name__ == "__main__":
    main()
