"""Outbound SMS. SMS_PROVIDER=console prints (dev); SMS_PROVIDER=twilio sends.

Twilio is called over its REST API with requests, so the twilio SDK is not
needed. Credentials come from TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN /
TWILIO_PHONE_FROM (a Twilio number or an approved alphanumeric sender ID).
"""
import os
from dataclasses import dataclass
from typing import Optional

import requests

TWILIO_MESSAGES_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


@dataclass
class SmsResult:
    ok: bool
    provider_ref: Optional[str] = None
    error: Optional[str] = None


def sms_provider() -> str:
    return os.getenv("SMS_PROVIDER", "console").strip().lower()


def send_sms(to_e164: str, body: str, session: Optional[requests.Session] = None) -> SmsResult:
    provider = sms_provider()
    if provider == "console":
        print(f"\n{'=' * 50}\n  SMS to {to_e164}:\n  {body}\n{'=' * 50}\n")
        return SmsResult(ok=True, provider_ref="console")

    if provider == "twilio":
        sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        sender = os.getenv("TWILIO_PHONE_FROM", "").strip()
        if not (sid and token and sender):
            return SmsResult(ok=False, error="Twilio is not configured (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_FROM).")
        http = session or requests
        try:
            resp = http.post(
                TWILIO_MESSAGES_URL.format(sid=sid),
                data={"To": to_e164, "From": sender, "Body": body},
                auth=(sid, token),
                timeout=20,
            )
            payload = resp.json() if resp.content else {}
        except (requests.RequestException, ValueError) as e:
            return SmsResult(ok=False, error=f"Twilio request failed: {e}")
        if resp.status_code >= 400:
            return SmsResult(ok=False, error=f"Twilio {resp.status_code}: {payload.get('message', resp.text[:200])}")
        return SmsResult(ok=True, provider_ref=payload.get("sid"))

    return SmsResult(ok=False, error=f"Unknown SMS_PROVIDER: {provider}")
