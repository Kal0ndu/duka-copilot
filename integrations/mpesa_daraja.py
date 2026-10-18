"""Safaricom Daraja client: M-Pesa Express (STK Push) and STK status query.

An STK push makes the owner's phone show an M-Pesa prompt; money only moves
if they enter their PIN. Status is confirmed by polling the STK query API,
so no public callback server is required (Daraja still demands a syntactically
valid HTTPS CallBackURL, which DARAJA_CALLBACK_URL supplies).

Environments:
  sandbox     https://sandbox.safaricom.co.ke (test credentials, no real money)
  production  https://api.safaricom.co.ke (refused while SANDBOX_ONLY=true)
  simulated   no network; every push succeeds — for tests and offline demos
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

BASE_URLS = {
    "sandbox": "https://sandbox.safaricom.co.ke",
    "production": "https://api.safaricom.co.ke",
}

# STK query result codes -> our states. Anything unlisted is 'failed'.
RESULT_STATES = {
    "0": "success",
    "1032": "cancelled",   # request cancelled by user
    "1037": "timeout",     # user could not be reached / did not respond
    "1019": "timeout",     # transaction expired
}
PROCESSING_ERROR_CODE = "500.001.1001"   # "The transaction is being processed"


class DarajaError(Exception):
    pass


@dataclass
class StkPushResult:
    merchant_request_id: str
    checkout_request_id: str
    customer_message: str


@dataclass
class StkQueryResult:
    state: str                 # pending | success | failed | cancelled | timeout
    result_code: Optional[str]
    result_desc: str
    mpesa_receipt: Optional[str] = None


def _phone_to_msisdn(phone_e164: str) -> str:
    """'+254712345678' -> '254712345678' (Daraja wants digits only)."""
    digits = "".join(ch for ch in phone_e164 if ch.isdigit())
    if not (len(digits) == 12 and digits.startswith("254")):
        raise DarajaError(f"Phone must be a Kenyan number in 2547XXXXXXXX form, got {phone_e164!r}")
    return digits


class DarajaClient:
    def __init__(
        self,
        env: str,
        consumer_key: str = "",
        consumer_secret: str = "",
        shortcode: str = "",
        passkey: str = "",
        callback_url: str = "",
        transaction_type: str = "CustomerPayBillOnline",
        sandbox_only: bool = True,
        session: Optional[requests.Session] = None,
        timeout: int = 30,
    ):
        env = (env or "sandbox").strip().lower()
        if env not in ("sandbox", "production", "simulated"):
            raise DarajaError(f"Unknown DARAJA_ENV: {env}")
        if env == "production" and sandbox_only:
            raise DarajaError("DARAJA_ENV=production is blocked while SANDBOX_ONLY=true.")
        self.env = env
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.shortcode = shortcode
        self.passkey = passkey
        self.callback_url = callback_url
        self.transaction_type = transaction_type
        self.http = session or requests.Session()
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_expires = 0.0

    @classmethod
    def from_env(cls, session: Optional[requests.Session] = None) -> "DarajaClient":
        return cls(
            env=os.getenv("DARAJA_ENV", "sandbox"),
            consumer_key=os.getenv("DARAJA_CONSUMER_KEY", "").strip(),
            consumer_secret=os.getenv("DARAJA_CONSUMER_SECRET", "").strip(),
            shortcode=os.getenv("DARAJA_SHORTCODE", "174379").strip(),
            passkey=os.getenv("DARAJA_PASSKEY", "").strip(),
            callback_url=os.getenv("DARAJA_CALLBACK_URL", "").strip(),
            transaction_type=os.getenv("DARAJA_TRANSACTION_TYPE", "CustomerPayBillOnline").strip(),
            sandbox_only=os.getenv("SANDBOX_ONLY", "true").lower() == "true",
            session=session,
        )

    # ---- configuration ----

    def missing_settings(self) -> list[str]:
        if self.env == "simulated":
            return []
        required = {
            "DARAJA_CONSUMER_KEY": self.consumer_key,
            "DARAJA_CONSUMER_SECRET": self.consumer_secret,
            "DARAJA_SHORTCODE": self.shortcode,
            "DARAJA_PASSKEY": self.passkey,
            "DARAJA_CALLBACK_URL": self.callback_url,
        }
        missing = [k for k, v in required.items() if not v]
        if self.callback_url and not self.callback_url.startswith("https://"):
            missing.append("DARAJA_CALLBACK_URL (must start with https://)")
        return missing

    @property
    def configured(self) -> bool:
        return not self.missing_settings()

    # ---- HTTP helpers ----

    @property
    def base_url(self) -> str:
        return BASE_URLS[self.env]

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires:
            return self._token
        try:
            resp = self.http.get(
                f"{self.base_url}/oauth/v1/generate",
                params={"grant_type": "client_credentials"},
                auth=(self.consumer_key, self.consumer_secret),
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise DarajaError(f"Could not reach Daraja: {e}") from e
        if resp.status_code != 200:
            raise DarajaError(f"Daraja auth failed ({resp.status_code}). Check DARAJA_CONSUMER_KEY/SECRET.")
        data = resp.json()
        self._token = data["access_token"]
        # Refresh a minute early.
        self._token_expires = time.time() + int(data.get("expires_in", 3599)) - 60
        return self._token

    def _password(self, timestamp: str) -> str:
        return base64.b64encode(f"{self.shortcode}{self.passkey}{timestamp}".encode()).decode()

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        try:
            resp = self.http.post(
                f"{self.base_url}{path}",
                json=body,
                headers={"Authorization": f"Bearer {self._access_token()}"},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise DarajaError(f"Could not reach Daraja: {e}") from e
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {"errorMessage": resp.text[:200]}

    # ---- API ----

    def stk_push(self, phone_e164: str, amount_kes: int, account_reference: str, description: str) -> StkPushResult:
        if amount_kes < 1:
            raise DarajaError("Amount must be at least KES 1.")
        msisdn = _phone_to_msisdn(phone_e164)
        if self.env == "simulated":
            ref = uuid.uuid4().hex[:10].upper()
            return StkPushResult(f"SIM-MR-{ref}", f"ws_CO_SIM_{ref}", "Simulated: prompt sent")

        missing = self.missing_settings()
        if missing:
            raise DarajaError("Daraja is not configured. Missing: " + ", ".join(missing))

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        status, data = self._post("/mpesa/stkpush/v1/processrequest", {
            "BusinessShortCode": self.shortcode,
            "Password": self._password(timestamp),
            "Timestamp": timestamp,
            "TransactionType": self.transaction_type,
            "Amount": int(amount_kes),
            "PartyA": msisdn,
            "PartyB": self.shortcode,
            "PhoneNumber": msisdn,
            "CallBackURL": self.callback_url,
            "AccountReference": (account_reference or "Duka")[:12],
            "TransactionDesc": (description or "Payment")[:13],
        })
        if status != 200 or str(data.get("ResponseCode")) != "0":
            msg = data.get("errorMessage") or data.get("ResponseDescription") or str(data)[:200]
            raise DarajaError(f"STK push rejected: {msg}")
        return StkPushResult(
            merchant_request_id=data.get("MerchantRequestID", ""),
            checkout_request_id=data["CheckoutRequestID"],
            customer_message=data.get("CustomerMessage", ""),
        )

    def stk_query(self, checkout_request_id: str) -> StkQueryResult:
        if self.env == "simulated":
            receipt = "SIM" + checkout_request_id[-7:]
            return StkQueryResult("success", "0", "Simulated payment completed", receipt)

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        status, data = self._post("/mpesa/stkpushquery/v1/query", {
            "BusinessShortCode": self.shortcode,
            "Password": self._password(timestamp),
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        })
        if data.get("errorCode") == PROCESSING_ERROR_CODE:
            return StkQueryResult("pending", None, data.get("errorMessage", "Still processing"))
        if "ResultCode" not in data:
            # Rate limits and transient errors: report as pending so the user can retry the check.
            return StkQueryResult("pending", None, data.get("errorMessage", f"Unexpected response ({status})"))
        code = str(data["ResultCode"])
        # The query API does not return the M-Pesa receipt number; that only
        # arrives on the callback, so it stays None here.
        return StkQueryResult(RESULT_STATES.get(code, "failed"), code, data.get("ResultDesc", ""))
