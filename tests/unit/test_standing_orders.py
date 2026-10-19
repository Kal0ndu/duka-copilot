"""Tests for core/standing_orders.py — scheduling, notifications, owner authorization."""
import sqlite3
from datetime import date, timedelta

import pytest

from auth.phone_utils import hash_phone
from core.standing_orders import PaymentNotAllowed, StandingOrderService, first_due_on_or_after, next_occurrence
from db.migrate import MigrationRunner
from integrations.mpesa_daraja import DarajaClient, DarajaError, StkPushResult, StkQueryResult
from integrations.sms import SmsResult

TODAY = date(2026, 10, 18)
OWNER_PHONE = "+254708374149"


class FakeDaraja:
    env = "sandbox"

    def __init__(self, push_error=None, query_state="success"):
        self.pushes = []
        self.push_error = push_error
        self.query_state = query_state

    def stk_push(self, phone, amount_kes, reference, description):
        if self.push_error:
            raise DarajaError(self.push_error)
        self.pushes.append((phone, amount_kes, reference))
        return StkPushResult("MR1", f"ws_CO_{len(self.pushes)}", "Success. Request accepted for processing")

    def stk_query(self, checkout_request_id):
        return StkQueryResult(self.query_state, "0" if self.query_state == "success" else "1032", "done")


@pytest.fixture
def env(tmp_path):
    path = str(tmp_path / "duka.db")
    MigrationRunner(path).run_pending()
    conn = sqlite3.connect(path)
    owner = conn.execute(
        "INSERT INTO app_user (phone_hash, display_name, display_token) VALUES (?, 'Owner', 'U1')",
        (hash_phone(OWNER_PHONE),),
    ).lastrowid
    viewer = conn.execute(
        "INSERT INTO app_user (phone_hash, display_name, display_token) VALUES (?, 'Viewer', 'U2')",
        (hash_phone("+254700000002"),),
    ).lastrowid
    conn.execute(
        "INSERT INTO business (business_id, public_ref, name_token, sector, country_code, currency_code, owner_user_id) "
        "VALUES (1, 'B1', 'BIZ_1', 'grocery', 'KE', 'KES', ?)", (owner,),
    )
    conn.execute(
        "INSERT INTO business_member (business_id, user_id, phone_hash, role) VALUES (1, ?, ?, 'viewer')",
        (viewer, hash_phone("+254700000002")),
    )
    conn.commit()
    conn.close()

    sms = []
    daraja = FakeDaraja()
    svc = StandingOrderService(
        path, daraja=daraja,
        sms_sender=lambda to, body: sms.append((to, body)) or SmsResult(True, "SM1"),
        today_fn=lambda: TODAY,
    )
    return {"svc": svc, "db": path, "owner": owner, "viewer": viewer, "sms": sms, "daraja": daraja}


def _rent(svc, owner, days=1, **kw):
    return svc.create_order(1, owner, "Shop rent", "rent", "paybill", "888880", 15000, "monthly",
                            TODAY + timedelta(days=days), account_reference="SHOP12", **kw)


class TestSchedule:
    def test_monthly_clamps_to_month_end(self):
        assert next_occurrence(date(2026, 1, 31), "monthly", 31) == date(2026, 2, 28)
        assert next_occurrence(date(2026, 2, 28), "monthly", 31) == date(2026, 3, 31)

    def test_past_start_does_not_backfill(self):
        assert first_due_on_or_after(date(2026, 1, 5), "monthly", TODAY) == date(2026, 11, 5)

    def test_run_is_idempotent_and_respects_reminder_window(self, env):
        svc = env["svc"]
        _rent(svc, env["owner"], days=1)
        svc.create_order(1, env["owner"], "KPLC", "utility", "paybill", "888880", 2000, "monthly",
                         TODAY + timedelta(days=10), account_reference="123")
        assert svc.run(1) == {"created": 1, "notified": 1}
        assert svc.run(1) == {"created": 0, "notified": 0}
        assert [p["label"] for p in svc.open_payments(1)] == ["Shop rent"]

    def test_paused_order_skips_pending_payment(self, env):
        svc = env["svc"]
        so = _rent(svc, env["owner"])
        svc.run(1)
        svc.set_order_status(1, so, "paused")
        assert svc.open_payments(1) == []


class TestValidation:
    def test_paybill_needs_account(self, env):
        with pytest.raises(ValueError):
            env["svc"].create_order(1, env["owner"], "x", "rent", "paybill", "888880", 100, "monthly", TODAY)

    def test_amount_over_cap_rejected(self, env):
        with pytest.raises(ValueError):
            env["svc"].create_order(1, env["owner"], "x", "rent", "till", "123456", 10**7, "monthly", TODAY)

    def test_cap_follows_owner_settings(self, env):
        from dataclasses import replace
        from core.owner_settings import OwnerPin, load_settings, save_settings
        OwnerPin(env["db"]).set_pin(1, "4826")
        # Raise the cap above the KES 25,000 default: a KES 40,000 order is now allowed.
        save_settings(env["db"], replace(load_settings(env["db"], 1), per_txn_cap_minor=5_000_000,
                                         daily_cap_minor=10_000_000), pin="4826")
        env["svc"].create_order(1, env["owner"], "Rent", "rent", "till", "123456", 40_000, "monthly", TODAY)
        # Lower it: KES 5,000 is now over the limit.
        save_settings(env["db"], replace(load_settings(env["db"], 1), per_txn_cap_minor=400_000), pin="4826")
        with pytest.raises(ValueError, match="4,000"):
            env["svc"].create_order(1, env["owner"], "x", "rent", "till", "123456", 5_000, "monthly", TODAY)

    def test_contact_must_be_login_phone(self, env):
        with pytest.raises(PaymentNotAllowed):
            env["svc"].set_contact(1, env["owner"], "0711111111")
        assert env["svc"].set_contact(1, env["owner"], "0708374149").endswith("149")


class TestNotifications:
    def test_sms_sent_to_owner_with_link_and_pin_warning(self, env, monkeypatch):
        monkeypatch.setenv("APP_BASE_URL", "https://duka.example")
        svc = env["svc"]
        svc.set_contact(1, env["owner"], OWNER_PHONE)
        _rent(svc, env["owner"])
        svc.run(1)
        assert len(env["sms"]) == 1
        to, body = env["sms"][0]
        assert to == OWNER_PHONE
        assert "https://duka.example/Standing_Orders?pay=" in body
        assert "never asks for your M-Pesa PIN" in body
        assert svc.unread_count(1, env["owner"]) == 1

    def test_no_sms_without_contact_but_in_app_still_created(self, env):
        svc = env["svc"]
        _rent(svc, env["owner"])
        svc.run(1)
        assert env["sms"] == []
        assert svc.unread_count(1, env["owner"]) == 1


class TestAuthorization:
    def _ready(self, env):
        svc = env["svc"]
        svc.set_contact(1, env["owner"], OWNER_PHONE)
        _rent(svc, env["owner"])
        svc.run(1)
        return svc, svc.open_payments(1)[0]["payment_id"]

    def test_owner_authorizes_then_pin_confirms_payment(self, env):
        svc, pid = self._ready(env)
        res = svc.authorize_and_push(pid, 1, env["owner"])
        assert res["status"] == "stk_sent"
        assert env["daraja"].pushes == [(OWNER_PHONE, 15000, "SHOP12")]
        assert svc.check_status(pid, 1)["state"] == "success"
        assert svc.history(1)[0]["status"] == "paid"

    def test_double_authorize_pushes_once(self, env):
        svc, pid = self._ready(env)
        svc.authorize_and_push(pid, 1, env["owner"])
        with pytest.raises(PaymentNotAllowed):
            svc.authorize_and_push(pid, 1, env["owner"])
        assert len(env["daraja"].pushes) == 1

    def test_viewer_cannot_authorize(self, env):
        svc, pid = self._ready(env)
        with pytest.raises(PaymentNotAllowed):
            svc.authorize_and_push(pid, 1, env["viewer"])
        assert env["daraja"].pushes == []

    def test_other_business_cannot_authorize(self, env):
        svc, pid = self._ready(env)
        with pytest.raises(PaymentNotAllowed):
            svc.authorize_and_push(pid, 2, env["owner"])

    def test_push_failure_marks_failed_and_allows_retry(self, env):
        svc, pid = self._ready(env)
        env["daraja"].push_error = "Daraja is down"
        with pytest.raises(PaymentNotAllowed):
            svc.authorize_and_push(pid, 1, env["owner"])
        assert svc.open_payments(1)[0]["status"] == "failed"
        env["daraja"].push_error = None
        assert svc.authorize_and_push(pid, 1, env["owner"])["status"] == "stk_sent"

    def test_cancelled_prompt_marks_failed(self, env):
        svc, pid = self._ready(env)
        env["daraja"].query_state = "cancelled"
        svc.authorize_and_push(pid, 1, env["owner"])
        assert svc.check_status(pid, 1)["state"] == "cancelled"
        assert svc.open_payments(1)[0]["status"] == "failed"

    def test_changed_login_phone_invalidates_contact(self, env):
        svc, pid = self._ready(env)
        conn = sqlite3.connect(env["db"])
        conn.execute("UPDATE app_user SET phone_hash = ? WHERE user_id = ?", (hash_phone("+254799999999"), env["owner"]))
        conn.commit()
        with pytest.raises(PaymentNotAllowed):
            svc.authorize_and_push(pid, 1, env["owner"])

    def test_agent_view_has_no_payment_destinations(self, env):
        svc, _ = self._ready(env)
        view = svc.priorities_for_agent(1)
        assert view and all("destination_number" not in p and "account_reference" not in p for p in view)


class TestDarajaClient:
    def test_production_blocked_while_sandbox_only(self):
        with pytest.raises(DarajaError):
            DarajaClient("production", sandbox_only=True)

    def test_missing_settings_reported(self):
        client = DarajaClient("sandbox", shortcode="174379", callback_url="http://insecure")
        missing = client.missing_settings()
        assert "DARAJA_CONSUMER_KEY" in missing and any("https" in m for m in missing)

    def test_stk_push_payload(self):
        sent = {}

        class Resp:
            def __init__(self, code, body):
                self.status_code, self._body = code, body

            def json(self):
                return self._body

        class Session:
            def get(self, url, **kw):
                sent["auth"] = kw["auth"]
                return Resp(200, {"access_token": "tok", "expires_in": "3599"})

            def post(self, url, json=None, headers=None, **kw):
                sent["url"], sent["body"], sent["headers"] = url, json, headers
                return Resp(200, {"ResponseCode": "0", "MerchantRequestID": "m", "CheckoutRequestID": "c",
                                  "CustomerMessage": "ok"})

        client = DarajaClient("sandbox", "key", "secret", "174379", "pk", "https://x.example/cb", session=Session())
        res = client.stk_push("+254708374149", 150, "SHOP-REFERENCE-LONG", "Shop rent payment")
        body = sent["body"]
        assert res.checkout_request_id == "c"
        assert sent["url"].endswith("/mpesa/stkpush/v1/processrequest")
        assert sent["headers"]["Authorization"] == "Bearer tok"
        assert body["PartyA"] == body["PhoneNumber"] == "254708374149"
        assert body["Amount"] == 150 and body["PartyB"] == "174379"
        assert len(body["AccountReference"]) <= 12 and len(body["TransactionDesc"]) <= 13
        import base64
        assert base64.b64decode(body["Password"]).decode() == f"174379pk{body['Timestamp']}"
