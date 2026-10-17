"""Tests for core/categoriser.py"""
import pytest
from core.categoriser import Categoriser, CategoryResult


class TestCategoriser:
    def test_rule_based_income(self):
        c = Categoriser()
        result = c.categorise(
            description="Customer payment via till",
            channel="till", direction="in",
            amount_minor=50000
        )
        assert isinstance(result, CategoryResult)
        assert result.category_code == "SALES_TILL"
        assert result.source == "rule"

    def test_rule_based_stock_expense(self):
        c = Categoriser()
        result = c.categorise(
            description="stock purchase from supplier",
            channel="send", direction="out",
            amount_minor=200000
        )
        assert result.category_code == "STOCK_PURCHASES"

    def test_categorise_batch(self):
        c = Categoriser()
        transactions = [
            {"description": "till payment", "channel": "till", "direction": "in", "amount_minor": 30000},
            {"description": "stock buy", "channel": "send", "direction": "out", "amount_minor": 50000},
            {"description": "kplc bill", "channel": "bill", "direction": "out", "amount_minor": 20000},
        ]
        results = c.categorise_batch(transactions)
        assert len(results) == 3
        codes = [r.category_code for r in results]
        assert "SALES_TILL" in codes
        assert "STOCK_PURCHASES" in codes
        assert "UTILITIES" in codes

    def test_empty_batch(self):
        c = Categoriser()
        results = c.categorise_batch([])
        assert results == []

    def test_uncategorised_preserved(self):
        c = Categoriser()
        result = c.categorise(
            description="blargle flump zanzibar nothing",
            channel="other", direction="out",
            amount_minor=1
        )
        assert result.category_code == "UNCATEGORISED"
