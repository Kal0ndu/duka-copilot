"""Tests for core/adapters/mobile_money_ke.py"""
import pytest
from core.adapters.mobile_money_ke import MobileMoneyKeAdapter


SAMPLE_CSV_BYTES = (
    b"Receipt No.,Completion Time,Details,Paid In,Withdrawn,Balance\r\n"
    b"ABC123,2025-01-15 08:30:00,Till Payment,5000,0,15000\r\n"
    b"DEF456,2025-01-15 09:00:00,Withdraw Agent,0,2000,13000\r\n"
)


class TestMobileMoneyKeAdapter:
    def test_parse_valid_csv(self):
        adapter = MobileMoneyKeAdapter()
        rows = adapter.parse(SAMPLE_CSV_BYTES)
        assert isinstance(rows, list)
        assert len(rows) == 2
        assert rows[0]["amount_minor"] == 500000

    def test_parse_empty_csv(self):
        adapter = MobileMoneyKeAdapter()
        rows = adapter.parse(b"")
        assert isinstance(rows, list)
        assert len(rows) == 0

    def test_parse_missing_columns(self):
        adapter = MobileMoneyKeAdapter()
        bad_csv = b"col1,col2\nval1,val2\n"
        with pytest.raises(ValueError, match="Unrecognized CSV format"):
            adapter.parse(bad_csv)

    def test_get_summary(self):
        adapter = MobileMoneyKeAdapter()
        rows = adapter.parse(SAMPLE_CSV_BYTES)
        summary = adapter.get_summary(rows)
        assert isinstance(summary, dict)
        assert summary["count"] == 2
