"""Unit tests for core/working_capital.py."""
import pytest
from core.working_capital import WorkingCapitalAnalyzer


@pytest.fixture
def wc_transactions():
    return [
        {"local_date": "2026-07-01", "amount": 5000.0, "direction": "in", "counterparty": "Shop Buyer A"},
        {"local_date": "2026-07-02", "amount": 3000.0, "direction": "in", "counterparty": "Shop Buyer B"},
        {"local_date": "2026-07-03", "amount": 4000.0, "direction": "out", "counterparty": "Flour Miller"},
    ]


def test_working_capital_metrics(wc_transactions):
    analyzer = WorkingCapitalAnalyzer(wc_transactions)
    metrics = analyzer.compute_working_capital_metrics()

    assert "total_receivables_kes" in metrics
    assert "total_payables_kes" in metrics
    assert "dso_days" in metrics
    assert "dpo_days" in metrics
    assert "cash_conversion_cycle_days" in metrics
    assert len(metrics["receivables_list"]) > 0
    assert len(metrics["payables_list"]) > 0


def test_credit_entry_reminder_format(wc_transactions):
    analyzer = WorkingCapitalAnalyzer(wc_transactions)
    recs, _ = analyzer.generate_credit_book()
    assert len(recs) > 0
    entry = recs[0]
    assert "Habari" in entry.reminder_msg
    assert "KES" in entry.reminder_msg
