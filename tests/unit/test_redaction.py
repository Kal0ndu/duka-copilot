"""Tests for core/redaction.py"""
import pytest
from core.redaction import Redactor, RedactionResult


class TestRedactor:
    def test_redact_phone_number(self):
        r = Redactor()
        result = r.redact("Call me on 0712345678")
        assert isinstance(result, RedactionResult)
        assert "0712345678" not in result.redacted
        assert "<PHONE_" in result.redacted

    def test_redact_kenyan_phone(self):
        r = Redactor()
        result = r.redact("M-PESA from 0722000000")
        assert "0722000000" not in result.redacted
        assert any("0722000000" == v for v in result.tokens.values())

    def test_redact_email(self):
        r = Redactor()
        result = r.redact("Email me at jane@example.com")
        assert "jane@example.com" not in result.redacted
        assert "<EMAIL_" in result.redacted

    def test_preserve_non_pii(self):
        r = Redactor()
        result = r.redact("Paid KSH 500 for stock")
        assert "stock" in result.redacted
        assert "500" not in result.redacted  # numeric reference pattern

    def test_redact_transactions_list(self):
        r = Redactor()
        txn = "Sent 500 to 0711222333 for rent"
        result = r.redact(txn)
        assert "0711222333" not in result.redacted

    def test_empty_text(self):
        r = Redactor()
        result = r.redact("")
        assert result.redacted == ""
        assert result.pii_found == []

    def test_none_text(self):
        r = Redactor()
        result = r.redact(None)
        assert result.redacted == ""
        assert result.pii_found == []
