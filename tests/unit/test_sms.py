"""Tests for integrations/sms.py"""
from integrations.sms import send_sms


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body, self.content, self.text = code, body, b"x", str(body)

    def json(self):
        return self._body


class _Session:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp


def test_console_provider(monkeypatch, capsys):
    monkeypatch.setenv("SMS_PROVIDER", "console")
    assert send_sms("+254708374149", "hi").ok
    assert "hi" in capsys.readouterr().out


def test_twilio_sends_via_rest(monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "twilio")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_PHONE_FROM", "+15550001111")
    session = _Session(_Resp(201, {"sid": "SM123"}))
    res = send_sms("+254708374149", "Rent due", session=session)
    url, kw = session.calls[0]
    assert res.ok and res.provider_ref == "SM123"
    assert url.endswith("/Accounts/ACtest/Messages.json")
    assert kw["data"] == {"To": "+254708374149", "From": "+15550001111", "Body": "Rent due"}
    assert kw["auth"] == ("ACtest", "tok")


def test_twilio_error_reported(monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "twilio")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_PHONE_FROM", "+15550001111")
    res = send_sms("+254708374149", "x", session=_Session(_Resp(400, {"message": "unverified number"})))
    assert not res.ok and "unverified number" in res.error


def test_twilio_missing_config(monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "twilio")
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    assert not send_sms("+254708374149", "x").ok
