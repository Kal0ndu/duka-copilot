"""Security tests: verify PII never leaks through redaction layer."""
import pytest
from core.redaction import Redactor


class TestRedactionSecurity:
    """Critical security checks — redaction must never fail."""

    def setup_method(self):
        self.r = Redactor()

    def test_no_phone_leak_in_output(self):
        inputs = [
            "+254712345678",
            "0712345678",
            "254712345678",
        ]
        for inp in inputs:
            result = self.r.redact(f"Call {inp} for details")
            assert inp not in result.redacted, f"Phone {inp} leaked!"

    def test_no_email_leak(self):
        emails = ["jane@example.com", "john.doe@co.ke", "test+tag@gmail.com"]
        for e in emails:
            result = self.r.redact(f"Email: {e}")
            assert e not in result.redacted, f"Email {e} leaked!"

    def test_redact_handles_none(self):
        result = self.r.redact(None)
        assert result.redacted == ""

    def test_redact_handles_empty(self):
        result = self.r.redact("")
        assert result.redacted == ""

    def test_redact_handles_only_pii(self):
        result = self.r.redact("0712345678")
        assert "0712345678" not in result.redacted

    def test_transactions_redaction_applied(self):
        txns = [
            {"date": "2026-07-01", "amount": 500, "counterparty": "+254712345678", "type": "credit"},
            {"date": "2026-07-01", "amount": -200, "counterparty": "john@doe.com", "type": "debit"},
        ]
        for txn in txns:
            r = self.r.redact(str(txn))
            assert "+254" not in r.redacted
            assert "@" not in r.redacted
